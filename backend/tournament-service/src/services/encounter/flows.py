import typing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from cashews import cache
from cashews.exceptions import CacheBackendInteractionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.core import errors, pagination, utils
from shared.core.enums import EncounterGameState
from shared.repository import (
    BracketEncounterRepository,
    EncounterGameTeamRepository,
    StageItemRepository,
    StageRepository,
    TeamRepository,
)
from shared.repository.stats_reads import MatchReadContext
from shared.schemas.catalog import CatalogEntityRead
from shared.schemas.match import MatchEventsRead
from shared.services.cache_generations import current, versioned
from shared.services.challonge_refs import resolve_encounter_challonge, resolve_tournament_challonge
from shared.services.match_reads import match_events_read, match_header_fields, match_statistics_read
from src import schemas
from src.core import config
from src.core.caching import single_flight
from src.services.bracket.advancement import SlotSource, resolve_slot_sources
from src.services.encounter.service import STRIP_ENTITIES, EncounterService, encounter_is_live, encounter_service
from src.services.map.flows import map_to_read
from src.services.team.flows import TeamFlowsService
from src.services.team.flows import flows_service as team_flows_service
from src.services.tournament.cache_resources import ENCOUNTERS, tournament_generations
from src.services.tournament.flows import TournamentFlowsService
from src.services.tournament.flows import flows_service as tournament_flows_service

# Every family embeds ``EncounterRead`` (and its ``MatchRead``, ``EncounterGameRead.map``/``.mode``). Their values are
# the dumped wire dicts in a persistent Redis that outlives a deploy, and cashews returns a value as it was stored, so
# a wire change to those models needs a new namespace (``native_``, then ``:v2``, ``:v3`` for ``played_at`` and
# ``is_live``, ``:v4`` for ``is_final`` and the overview's counts, ``:v5``/insights ``:v2`` for storing the wire dict
# instead of the pickled model), not a TTL wait. The key names EVERY query param that changes the SQL: one without the
# game served the first game's page to every other game for the whole TTL. The viewer is in it for ``scope=my_team``
# only: every other scope is passed ``None`` (``scope_viewer``), so logged-in readers share one entry.
# ``ENCOUNTERS`` (``tournament/cache_resources.py``) names the writes that miss all three;
# ``tests/test_encounter_cache_namespaces.py`` pins that against the keys cashews renders from these templates.
_ENCOUNTER_QUERY_KEY = (
    "{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:"
    "{params.entities}:{params.only_count}:{params.query}:{params.fields}:{params.stage_id}:{params.stage_item_id}:"
    "{params.best_of}:{params.status}:{params.has_logs}:{params.is_final}:{params.is_upset}:{params.closeness_min}:"
    "{params.closeness_max}:{params.scope}:{params.discipline}:{params.slot_count}:{viewer_auth_user_id}"
)
ENCOUNTERS_CACHE_KEY = f"native_encounters:v5:{_ENCOUNTER_QUERY_KEY}"
ENCOUNTERS_OVERVIEW_CACHE_KEY = f"native_encounters_overview:v5:{_ENCOUNTER_QUERY_KEY}"
ENCOUNTERS_INSIGHTS_CACHE_KEY = f"native_encounters_insights:v2:{_ENCOUNTER_QUERY_KEY}"

#: The entities an encounter read honours: all a cached read's key keeps of the client's list (``canonical_entities``).
READ_ENTITIES = frozenset({"tournament", "teams", "matches", "stage", "stage_item"})


def scope_viewer(params: schemas.EncounterSearchParams, viewer_auth_user_id: int | None) -> int | None:
    """The viewer an encounter read depends on: ``scope=my_team``'s, nobody's for any other scope."""
    return viewer_auth_user_id if params.scope == "my_team" else None


def _seats(encounter: models.Encounter) -> list[models.EncounterTeam]:
    """The live seats in slot order. Eager-loaded by ``encounter_entities``."""
    return sorted((seat for seat in encounter.teams if seat.active), key=lambda seat: seat.slot)


def seat_to_read(seat: models.EncounterTeam, team: schemas.TeamRead | None = None) -> schemas.EncounterTeamRead:
    """One participation as the wire names it."""
    return schemas.EncounterTeamRead(
        id=seat.id,
        slot=seat.slot,
        team_id=seat.team_id,
        name=seat.name,
        seed=seat.seed,
        score=seat.score,
        placement=seat.placement,
        active=seat.active,
        team=team,
    )


def _position_fields(position: models.BracketEncounter | None) -> dict[str, typing.Any]:
    """The bracket coordinate from ``tournament.bracket_encounter``: an
    encounter with no position reads as round 0 and no stage."""
    return {
        "round": 0 if position is None else position.round,
        "stage_id": None if position is None else position.stage_id,
        "stage_item_id": None if position is None else position.stage_item_id,
    }


def to_summary(
    encounter: models.Encounter, position: models.BracketEncounter | None = None
) -> schemas.EncounterSummaryRead:
    return schemas.EncounterSummaryRead(
        **encounter.to_dict(),
        scoring_preset=encounter.scoring_preset,
        **_position_fields(position),
        teams=[seat_to_read(seat) for seat in _seats(encounter)],
    )


def _saved_view_to_read(saved_view: models.EncounterSavedView) -> schemas.EncounterSavedViewRead:
    return schemas.EncounterSavedViewRead(
        id=saved_view.id,
        workspace_id=saved_view.workspace_id,
        name=saved_view.name,
        filters=schemas.EncounterFiltersRead.model_validate(saved_view.filters_json or {}),
        sort_order=saved_view.sort_order,
    )


def _games(encounter: models.Encounter) -> list[models.EncounterGame]:
    """The series' positions in order. Cancelled ones are history, not the live series. Eager-loaded with
    ``matches``."""
    return [
        game
        for game in sorted(encounter.games, key=lambda game: (game.position, game.id or 0))
        if game.state != EncounterGameState.CANCELLED
    ]


@dataclass(frozen=True, slots=True)
class _Facts:
    """What an ``EncounterRead`` reads besides its own row, fetched for every row of a page at once -- one statement
    per kind -- so a page costs the same statements at any size. Each map holds only what ``entities`` asked for."""

    positions: typing.Mapping[int, models.BracketEncounter]
    stages: typing.Mapping[int, schemas.StageSummaryRead]
    stage_items: typing.Mapping[int, schemas.StageItemSummaryRead]
    tournaments: typing.Mapping[int, schemas.TournamentRead]
    teams: typing.Mapping[int, schemas.TeamRead]
    #: By match id.
    matches: typing.Mapping[int, schemas.MatchRead]
    #: By game id.
    game_lines: typing.Mapping[int, list[schemas.EncounterGameTeamRead]]
    # The browse's own facts; a match's nested encounter goes without them.
    challonge_match_ids: typing.Mapping[int, int] = field(default_factory=dict)
    slot_sources: typing.Mapping[int, list[SlotSource]] = field(default_factory=dict)
    played_at: typing.Mapping[int, datetime | None] = field(default_factory=dict)
    is_final: typing.Mapping[int, bool] = field(default_factory=dict)


def _encounter_read(
    encounter: models.Encounter, entities: list[str], facts: _Facts, now: datetime
) -> schemas.EncounterRead:
    """One row as ``EncounterRead``: no IO, everything it reads is already in ``facts``."""
    position = facts.positions.get(encounter.id)
    games_read: list[schemas.EncounterGameRead] = []
    matches_read: list[schemas.MatchRead] = []
    if "matches" in entities:
        matches_read = [facts.matches[match.id] for match in encounter.matches if match.id in facts.matches]
        # Same entity switch as ``matches``: the read carries both what the tournament DECIDED per position (games)
        # and what a parsed log OBSERVED (matches), so a position can be named before any log exists.
        games_read = [
            schemas.EncounterGameRead(
                id=game.id,
                position=game.position,
                map_id=game.map_id,
                map=map_to_read(game.map, []) if game.map is not None else None,
                mode_id=game.mode_id,
                mode=CatalogEntityRead.from_entity(game.mode, with_parent=False) if game.mode is not None else None,
                state=game.state.value,
                result_source=game.result_source.value if game.result_source is not None else None,
                result_version=game.result_version,
                confirmed_at=game.confirmed_at,
                teams=facts.game_lines.get(game.id, []),
            )
            for game in _games(encounter)
        ]

    encounter_dict = encounter.to_dict()
    # ``challonge_id`` (a bracket key) is derived from challonge_match_mapping; ``None`` when not prefetched.
    encounter_dict["challonge_id"] = facts.challonge_match_ids.get(encounter.id)
    # Computed properties are not part of the persisted column dictionary.
    encounter_dict["has_logs"] = encounter.has_logs
    encounter_dict["scoring_preset"] = encounter.scoring_preset
    encounter_dict["is_live"] = encounter_is_live(encounter, now)
    encounter_dict["played_at"] = facts.played_at.get(encounter.id)
    encounter_dict["is_final"] = facts.is_final.get(encounter.id, False)

    return schemas.EncounterRead(
        **encounter_dict,
        **_position_fields(position),
        games=games_read,
        stage=facts.stages.get(position.stage_id) if position is not None and position.stage_id else None,
        stage_item=(
            facts.stage_items.get(position.stage_item_id) if position is not None and position.stage_item_id else None
        ),
        tournament=facts.tournaments.get(encounter.tournament_id) if "tournament" in entities else None,
        # Every live seat is on the wire; the source team is expanded only for the ``teams`` entity.
        teams=[
            seat_to_read(seat, facts.teams.get(seat.team_id) if "teams" in entities and seat.team_id else None)
            for seat in _seats(encounter)
        ],
        matches=matches_read,
        sources=[
            schemas.EncounterSlotSourceRead(
                encounter_id=source.encounter_id,
                source_position=source.source_position,
                slot=source.slot,
            )
            for source in facts.slot_sources.get(encounter.id, ())
        ],
    )


class EncounterFlowsService:
    """Read orchestration for the encounter/match public surface: ORM rows in,
    ``schemas.*Read`` out. Every encounter read goes through ``_facts``, one
    statement per kind for a whole page, so a page costs the same at any size.

    Pure serialization helpers stay module-level: they take no session.
    """

    def __init__(
        self,
        *,
        encounters: EncounterService = encounter_service,
        teams: TeamFlowsService = team_flows_service,
        tournaments: TournamentFlowsService = tournament_flows_service,
        game_teams: EncounterGameTeamRepository = EncounterGameTeamRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        team_repo: TeamRepository = TeamRepository(),
    ) -> None:
        self.encounters = encounters
        self.teams = teams
        self.tournaments = tournaments
        self.game_team_repo = game_teams
        self.bracket_encounter_repo = bracket_encounter_repo
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.team_repo = team_repo

    async def _facts(
        self,
        session: AsyncSession,
        encounters: typing.Sequence[models.Encounter],
        entities: list[str],
        *,
        page: bool,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
        team_cache: dict[int, schemas.TeamRead] | None = None,
    ) -> _Facts:
        """Everything ``encounters`` read besides their rows, one statement per kind. ``page`` adds the browse's own
        facts: the challonge keys, the slot sources, the play date and the final flag."""
        ids = [encounter.id for encounter in encounters]
        positions = await self.bracket_encounter_repo.get_many_by(session, models.BracketEncounter.encounter_id, ids)
        stages: dict[int, schemas.StageSummaryRead] = {}
        if "stage" in entities:
            stage_ids = {position.stage_id for position in positions.values() if position.stage_id is not None}
            stages = {
                # A nested stage's challonge ref is derived at the top-level tournament read, not here.
                row.id: schemas.StageSummaryRead.model_validate(row, from_attributes=True).model_copy(
                    update={"challonge_id": None, "challonge_slug": None}
                )
                for row in await self.stage_repo.bulk_get(session, list(stage_ids))
            }
        stage_items: dict[int, schemas.StageItemSummaryRead] = {}
        if "stage_item" in entities:
            item_ids = {position.stage_item_id for position in positions.values() if position.stage_item_id is not None}
            stage_items = {
                row.id: schemas.StageItemSummaryRead.model_validate(row, from_attributes=True)
                for row in await self.stage_item_repo.bulk_get(session, list(item_ids))
            }

        tournaments = {} if tournament_cache is None else tournament_cache
        if "tournament" in entities:
            nested = utils.prepare_entities(entities, "tournament")
            missing = {
                encounter.tournament_id: encounter.tournament
                for encounter in encounters
                if encounter.tournament_id not in tournaments
            }
            refs = await resolve_tournament_challonge(session, list(missing)) if page and missing else {}
            for tournament_id, tournament in missing.items():
                tournaments[tournament_id] = await self.tournaments.to_pydantic(
                    session, tournament, nested, challonge_ref=refs.get(tournament_id)
                )

        teams = {} if team_cache is None else team_cache
        if "teams" in entities:
            nested = utils.prepare_entities(entities, "teams")
            missing_teams = {
                seat.team_id for encounter in encounters for seat in _seats(encounter) if seat.team_id is not None
            } - teams.keys()
            if missing_teams:
                # The teams' nested entities (``tournament``, ``players``, ``captain``) are eager-loaded here, or
                # ``to_pydantic`` touches unloaded relationships (``MissingGreenlet``). ``populate_existing`` makes
                # the options apply: a load otherwise hands back an identity-mapped row as it was FIRST loaded (e.g.
                # bare, via a native match read) and ignores them.
                rows = (
                    (
                        await session.execute(
                            self.team_repo.select()
                            .where(models.Team.id.in_(missing_teams))
                            .options(*TeamRepository.team_entities(nested))
                            .execution_options(populate_existing=True)
                        )
                    )
                    .unique()
                    .scalars()
                    .all()
                )
                # The division grid once per tournament, not once per team.
                for row, read in zip(rows, await self.teams.to_pydantic_many(session, rows, nested), strict=True):
                    teams[row.id] = read

        matches: dict[int, schemas.MatchRead] = {}
        game_lines: dict[int, list[schemas.EncounterGameTeamRead]] = {}
        if "matches" in entities:
            nested = utils.prepare_entities(entities, "matches")
            match_ids = [match.id for encounter in encounters for match in encounter.matches]
            if match_ids:
                for context in await self.encounters.get_match_bulk(session, match_ids, nested):
                    matches[context.match.id] = await self.to_pydantic_match(
                        session, context, nested, team_cache=teams, tournament_cache=tournaments
                    )
            game_ids = [game.id for encounter in encounters for game in _games(encounter)]
            for line in await self.game_team_repo.list_for_games(session, game_ids):
                game_lines.setdefault(line.game_id, []).append(
                    schemas.EncounterGameTeamRead(
                        encounter_team_id=line.encounter_team_id,
                        score=line.score,
                        placement=line.placement,
                        column_values=dict(line.column_values or {}),
                        starting_side=line.starting_side,
                        replay_code=line.replay_code,
                    )
                )

        facts = _Facts(positions, stages, stage_items, tournaments, teams, matches, game_lines)
        if not page:
            return facts
        return replace(
            facts,
            challonge_match_ids=await resolve_encounter_challonge(session, ids),
            slot_sources=await resolve_slot_sources(session, ids),
            played_at=await self.encounters.played_at_by_encounter(session, ids),
            is_final=await self.encounters.is_final_by_encounter(session, ids),
        )

    async def _reads(
        self,
        session: AsyncSession,
        encounters: typing.Sequence[models.Encounter],
        entities: list[str],
        *,
        page: bool,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
        team_cache: dict[int, schemas.TeamRead] | None = None,
    ) -> list[schemas.EncounterRead]:
        """``encounters`` as ``EncounterRead`` with ``entities``, in order (see ``_facts`` for ``page``)."""
        if not encounters:
            return []
        facts = await self._facts(
            session, encounters, entities, page=page, tournament_cache=tournament_cache, team_cache=team_cache
        )
        now = datetime.now(UTC)
        return [_encounter_read(encounter, entities, facts, now) for encounter in encounters]

    async def to_pydantic(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
        entities: list[str],
        *,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
        team_cache: dict[int, schemas.TeamRead] | None = None,
    ) -> schemas.EncounterRead:
        """One encounter as ``EncounterRead`` with ``entities``, the way a match nests it: without the browse's page
        facts (``challonge_id``, ``sources``, ``played_at``, ``is_final``)."""
        [read] = await self._reads(
            session, [encounter], entities, page=False, tournament_cache=tournament_cache, team_cache=team_cache
        )
        return read

    async def _match_fields(
        self,
        session: AsyncSession,
        match: MatchReadContext,
        entities: list[str],
        *,
        team_cache: dict[int, schemas.TeamRead] | None = None,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
    ) -> dict[str, typing.Any]:
        """The ``MatchRead`` fields of one context: the shared header, and the encounter when asked for."""
        encounter: schemas.EncounterRead | None = None
        if "encounter" in entities:
            encounter = await self.to_pydantic(
                session,
                match.encounter,
                [
                    entity
                    for entity in utils.prepare_entities(entities, "encounter")
                    if entity != "matches" and not entity.startswith("matches.")
                ],
                tournament_cache=tournament_cache,
                team_cache=team_cache,
            )
        return {
            **match_header_fields(
                match,
                with_map="map" in entities,
                with_parent="parent" in utils.prepare_entities(entities, "map"),
            ),
            "encounter": encounter,
        }

    async def to_pydantic_match(
        self,
        session: AsyncSession,
        match: MatchReadContext,
        entities: list[str],
        *,
        team_cache: dict[int, schemas.TeamRead] | None = None,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
    ) -> schemas.MatchRead:
        """Serialize one native match: its participants, official result lines and observed team facts."""
        return schemas.MatchRead(
            **await self._match_fields(
                session, match, entities, team_cache=team_cache, tournament_cache=tournament_cache
            )
        )

    async def get_encounter(
        self, session: AsyncSession, encounter_id: int, entities: list[str]
    ) -> schemas.EncounterRead:
        """One encounter as ``EncounterRead`` with ``entities``; 404 when it does not exist."""
        encounter = await self.encounters.get_encounter(session, encounter_id, entities)
        if not encounter:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Encounter with id {encounter_id} not found")],
            )
        [read] = await self._reads(session, [encounter], entities, page=True)
        return read

    async def get_all_encounters(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> pagination.Paginated[schemas.EncounterRead]:
        """One page of encounters matching ``params``, serialized. Uncached: ``list_encounters`` is the cached read."""
        encounters, total = await self.encounters.get_all_encounters(
            session,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
        )
        return pagination.Paginated(
            total=total,
            per_page=params.per_page,
            page=params.page,
            results=await self._reads(session, encounters, params.entities, page=True),
        )

    async def get_saved_views(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> list[schemas.EncounterSavedViewRead]:
        views = await self.encounters.get_saved_views(session, workspace_id=workspace_id, auth_user_id=auth_user_id)
        return [_saved_view_to_read(view) for view in views]

    async def save_view(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
        data: schemas.EncounterSavedViewCreate,
    ) -> schemas.EncounterSavedViewRead:
        """A new saved view; 409 when its name is taken or the caller keeps too many (``create_saved_view``)."""
        saved_view = await self.encounters.create_saved_view(
            session,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
            name=data.name,
            filters=data.filters.model_dump(exclude_none=True),
        )
        return _saved_view_to_read(saved_view)

    async def delete_saved_view(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
        saved_view_id: int,
    ) -> None:
        await self.encounters.delete_saved_view(
            session,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
            saved_view_id=saved_view_id,
        )

    async def get_encounters_overview(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> schemas.EncounterOverviewRead:
        """The browse's counts and live strip under ``params`` (``EncounterOverviewRead``). Uncached:
        ``encounters_overview`` is the cached read."""
        data = await self.encounters.get_overview_data(
            session,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
        )
        return schemas.EncounterOverviewRead(
            counts=schemas.EncounterCountsRead(**data["counts"]),
            completed_with_logs=data["completed_with_logs"],
            recent_completed=data["recent_completed"],
            live=await self._reads(session, data["live"], STRIP_ENTITIES, page=True),
        )

    async def get_encounters_insights(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> schemas.EncounterInsightsRead:
        """The analytics of the completed encounters under ``params`` (``EncounterInsightsRead``). Uncached:
        ``insights_page`` is the cached read."""
        data = await self.encounters.get_insights_data(
            session,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
        )
        return schemas.EncounterInsightsRead(
            completed=data["completed"],
            avg_closeness=data["avg_closeness"],
            closeness_histogram=[
                schemas.EncounterHistogramBucketRead(start=start, end=end, count=count)
                for start, end, count in data["closeness_histogram"]
            ],
            score_lines=[
                schemas.EncounterScoreLineRead(winner=winner, loser=loser, count=count)
                for winner, loser, count in data["score_lines"]
            ],
            stage_kinds=[schemas.EncounterStageKindRead(kind=kind, count=count) for kind, count in data["stage_kinds"]],
            hot_maps=[schemas.EncounterMapMetricRead(name=name, count=count) for name, count in data["hot_maps"]],
            closest=await self._reads(session, data["closest"], STRIP_ENTITIES, page=True),
            avg_series_seconds=data["avg_series_seconds"],
            multi_map=data["multi_map"],
            sweeps=data["sweeps"],
            went_distance=data["went_distance"],
        )

    # The cached families: each stores its builder's wire dict (``exclude_none``, as the subjects send it), so a hit
    # is a plain unpickle with no model to rebuild. Pass the viewer through ``scope_viewer`` and the entities through
    # ``canonical_entities(..., READ_ENTITIES)``: both are in the key. No ``lock=True``: cashews builds the herd-lock
    # key WITHOUT the ``prefix``, and this codebase routes backends purely by key prefix (no default backend), so the
    # lock raises NotConfiguredError -- ``single_flight`` coalesces the list's and the overview's herds instead.
    @versioned(
        generations=tournament_generations("{params.tournament_id}", ENCOUNTERS),
        ttl=config.settings.encounters_cache_ttl,
        key=ENCOUNTERS_CACHE_KEY,
        prefix="fastapi:",
    )
    async def encounters_page(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        page = await self.get_all_encounters(session, params, workspace_id, viewer_auth_user_id)
        return page.model_dump(mode="json", exclude_none=True)

    @versioned(
        generations=tournament_generations("{params.tournament_id}", ENCOUNTERS),
        ttl=config.settings.encounters_cache_ttl,
        key=ENCOUNTERS_OVERVIEW_CACHE_KEY,
        prefix="fastapi:",
    )
    async def overview_page(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        overview = await self.get_encounters_overview(session, params, workspace_id, viewer_auth_user_id)
        return overview.model_dump(mode="json", exclude_none=True)

    @versioned(
        generations=tournament_generations("{params.tournament_id}", ENCOUNTERS),
        ttl=config.settings.encounters_cache_ttl,
        key=ENCOUNTERS_INSIGHTS_CACHE_KEY,
        prefix="fastapi:",
    )
    async def insights_page(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        insights = await self.get_encounters_insights(session, params, workspace_id, viewer_auth_user_id)
        return insights.model_dump(mode="json", exclude_none=True)

    async def list_encounters(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        params: schemas.EncounterSearchParams,
        *,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """``rpc.tournament.list_encounters``: the cached page, built once per burst of identical requests."""
        viewer = scope_viewer(params, viewer_auth_user_id)
        return await self._coalesced(self.encounters_page, session_maker, params, workspace_id, viewer)

    async def encounters_overview(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        params: schemas.EncounterSearchParams,
        *,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """``rpc.tournament.encounters_overview``: the cached overview, built once per burst of identical requests.

        Outside ``scope=my_team`` the overview is viewer-agnostic but for its ``my_team`` count, so it is cached
        without the viewer (``my_team`` 0) and a signed-in viewer's own count is counted on top.
        """
        viewer = scope_viewer(params, viewer_auth_user_id)
        overview = await self._coalesced(self.overview_page, session_maker, params, workspace_id, viewer)
        if viewer_auth_user_id is None or viewer is not None:
            return overview
        async with session_maker() as session:
            my_team = await self.encounters.get_my_team_count(
                session, params, workspace_id=workspace_id, viewer_auth_user_id=viewer_auth_user_id
            )
        # A copy: the cached value is every concurrent follower's too.
        return {**overview, "counts": {**overview["counts"], "my_team": my_team}}

    async def _coalesced(
        self,
        read: typing.Callable[..., typing.Awaitable[dict[str, typing.Any]]],
        session_maker: async_sessionmaker[AsyncSession],
        params: schemas.EncounterSearchParams,
        workspace_id: int | None,
        viewer_auth_user_id: int | None,
    ) -> dict[str, typing.Any]:
        """``read`` through ``single_flight``, keyed like its cache key and the generations in it."""
        try:
            generation = await current(*tournament_generations(str(params.tournament_id), ENCOUNTERS))
        except CacheBackendInteractionError:
            generation = None  # the read bypasses the cache too; coalescing is all that is left

        async def build() -> dict[str, typing.Any]:
            async with session_maker() as session:
                return await read(session, params, workspace_id, viewer_auth_user_id)

        flight = (read.__name__, generation, workspace_id, viewer_auth_user_id, repr(params))
        return await single_flight(flight, build)

    async def get_all_matches(
        self, session: AsyncSession, params: schemas.MatchSearchParams, workspace_id: int | None = None
    ) -> pagination.Paginated[schemas.MatchRead]:
        """One page of matches matching ``params``, serialized."""
        matches, total = await self.encounters.get_all_matches(session, params, workspace_id=workspace_id)
        team_cache: dict[int, schemas.TeamRead] = {}
        tournament_cache: dict[int, schemas.TournamentRead] = {}
        return pagination.Paginated(
            total=total,
            per_page=params.per_page,
            page=params.page,
            results=[
                await self.to_pydantic_match(
                    session,
                    match,
                    params.entities,
                    team_cache=team_cache,
                    tournament_cache=tournament_cache,
                )
                for match in matches
            ],
        )

    async def get_match(
        self,
        session: AsyncSession,
        match_id: int,
        entities: list[str],
        workspace_id: int | None = None,
    ) -> schemas.MatchRead:
        """One match as ``MatchRead`` with ``entities``; 404 when it is not readable."""
        match = await self._get_context(session, match_id, entities, workspace_id)
        return await self.to_pydantic_match(session, match, entities)

    @cache(
        ttl=config.settings.match_cache_ttl,
        # No tournament_id in the args, so this key can't carry a tournament's
        # cache generations — staleness is bounded by the short TTL.
        # ``native_`` namespaces the participant/fact document shape: a cached value of another shape is never read.
        key="native_match_stats:v2:{match_id}:{entities}:{workspace_id}",
        prefix="fastapi:",
    )
    async def get_match_with_stats(
        self,
        session: AsyncSession,
        match_id: int,
        entities: list[str],
        workspace_id: int | None = None,
    ) -> schemas.MatchReadWithStats:
        """One match with its native statistics document (participants, members, segments, facts); 404 when absent."""
        match = await self._get_context(session, match_id, entities, workspace_id)
        return schemas.MatchReadWithStats(
            **await self._match_fields(session, match, entities),
            statistics=await match_statistics_read(session, match_id),
        )

    @cache(
        ttl=config.settings.match_cache_ttl,
        key="native_match_events:{match_id}:{workspace_id}",
        prefix="fastapi:",
    )
    async def get_match_kill_feed(
        self,
        session: AsyncSession,
        match_id: int,
        workspace_id: int | None = None,
    ) -> MatchEventsRead:
        """A match's whole event timeline, chronological, with the characters its events name.

        Validates the match exists within the (optional) workspace scope -- mirrors
        ``get_match_with_stats`` so event data can't cross workspace boundaries. Immutable
        once parsed, so it reuses the short match cache TTL.
        """
        # 404s if missing / out of workspace scope
        match = await self._get_context(session, match_id, [], workspace_id)
        return await match_events_read(session, match)

    async def _get_context(
        self, session: AsyncSession, match_id: int, entities: list[str], workspace_id: int | None
    ) -> MatchReadContext:
        match = await self.encounters.get_match(session, match_id, entities, workspace_id=workspace_id)
        if not match:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Match with id {match_id} not found")],
            )
        return match


flows_service = EncounterFlowsService()
