import typing

from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import EncounterGameState
from shared.services.bracket.advancement import SlotSource, resolve_slot_sources
from shared.services.challonge_refs import (
    ChallongeRef,
    resolve_encounter_challonge,
    resolve_tournament_challonge,
)
from src import models, schemas
from src.core import config, enums, errors, pagination, utils
from src.services.encounter.service import EncounterService, encounter_service
from src.services.map.flows import MapFlowsService, map_to_read
from src.services.map.flows import flows_service as map_flows_service
from src.services.team.flows import TeamFlowsService
from src.services.team.flows import flows_service as team_flows_service
from src.services.tournament.flows import TournamentFlowsService
from src.services.tournament.flows import flows_service as tournament_flows_service


def to_summary(encounter: models.Encounter) -> schemas.EncounterSummaryRead:
    return schemas.EncounterSummaryRead(
        **encounter.to_dict(),
        score=schemas.Score(home=encounter.home_score, away=encounter.away_score),
    )


def _saved_view_to_read(saved_view: models.EncounterSavedView) -> schemas.EncounterSavedViewRead:
    return schemas.EncounterSavedViewRead(
        id=saved_view.id,
        workspace_id=saved_view.workspace_id,
        name=saved_view.name,
        filters=schemas.EncounterFiltersRead.model_validate(saved_view.filters_json or {}),
        sort_order=saved_view.sort_order,
    )


def create_team_with_match_stats(
    team: schemas.TeamRead,
    team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]],
) -> schemas.TeamWithMatchStats:
    """
    Creates a TeamWithMatchStats schema from a TeamRead schema and a dictionary of team statistics.

    Parameters:
        team (schemas.TeamRead): The team data.
        team_stats (dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]]):
            A dictionary where the key is the player user ID and the value is a tuple containing:
                - A dictionary of round numbers to dictionaries of log stats names and their values.
                - A dictionary of round numbers to lists of hero statistics.

    Returns:
        schemas.TeamWithMatchStats: The team data with match statistics included.
    """
    return schemas.TeamWithMatchStats(
        **team.model_dump(exclude={"players"}),
        players=[
            schemas.PlayerWithMatchStats(
                **player.model_dump(),
                stats=team_stats[player.user_id][0],
                heroes=team_stats[player.user_id][1],  # type: ignore
            )
            for player in team.players
            if team_stats[player.user_id][1]
        ],
    )


class EncounterFlowsService:
    """Read orchestration for the encounter/match public surface: ORM rows in,
    ``schemas.*Read`` out, with the batched prefetches the list and overview
    pages need so ``to_pydantic`` never fires a query per row.

    Pure serialization helpers (``to_summary``, ``create_team_with_match_stats``)
    stay module-level: they take no session and other modules import them
    directly.
    """

    def __init__(
        self,
        *,
        encounters: EncounterService = encounter_service,
        maps: MapFlowsService = map_flows_service,
        teams: TeamFlowsService = team_flows_service,
        tournaments: TournamentFlowsService = tournament_flows_service,
    ) -> None:
        self.encounters = encounters
        self.maps = maps
        self.teams = teams
        self.tournaments = tournaments

    async def to_pydantic(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
        entities: list[str],
        *,
        challonge_match_ids: typing.Mapping[int, int] | None = None,
        tournament_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None,
        slot_sources: typing.Mapping[int, list[SlotSource]] | None = None,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
        team_cache: dict[int, schemas.TeamRead] | None = None,
    ) -> schemas.EncounterRead:
        """
        Converts an Encounter model instance to a Pydantic schema (EncounterRead), including related entities.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            encounter (models.Encounter): The Encounter model instance to convert.
            entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).
            challonge_match_ids: Optional prefetched ``encounter_id -> challonge_match_id``
                map DERIVED from ``challonge_match_mapping`` (see
                ``shared.services.challonge_refs``). The KEPT ``challonge_id`` response
                field (a bracket key for the frontend) is populated from it instead of
                the deprecated ``encounter.challonge_id`` column; omitted → ``None``.
            tournament_challonge_refs: Optional prefetched ``tournament_id -> (challonge_id,
                slug)`` map used the same way for the nested ``tournament``.

            slot_sources: Optional prefetched ``target encounter_id -> incoming
                advancement edges`` map (see ``resolve_slot_sources``). Populates the
                ``sources`` field a reader labels an unresolved bracket slot from;
                omitted → empty, which reads as "the bracket's shape is unknown".

        Returns:
            schemas.EncounterRead: The Pydantic schema representing the encounter.
        """
        stage: schemas.StageSummaryRead | None = None
        stage_item: schemas.StageItemSummaryRead | None = None
        tournament: schemas.TournamentRead | None = None
        home_team: schemas.TeamRead | None = None
        away_team: schemas.TeamRead | None = None
        matches_read: list[schemas.MatchRead] = []
        games_read: list[schemas.EncounterGameRead] = []

        if "stage" in entities and encounter.stage is not None:
            # Nested stage challonge is derived at the top-level tournament read, not
            # here — override to None so the legacy ``stage`` columns are never read.
            stage = schemas.StageSummaryRead.model_validate(encounter.stage, from_attributes=True).model_copy(
                update={"challonge_id": None, "challonge_slug": None}
            )
        if "stage_item" in entities and encounter.stage_item is not None:
            stage_item = schemas.StageItemSummaryRead.model_validate(encounter.stage_item, from_attributes=True)
        if "tournament" in entities:
            nested_tournament = utils.prepare_entities(entities, "tournament")
            cached_tournament = tournament_cache.get(encounter.tournament_id) if tournament_cache is not None else None
            if cached_tournament is not None:
                tournament = cached_tournament
            else:
                tournament = await self.tournaments.to_pydantic(
                    session,
                    encounter.tournament,
                    nested_tournament,
                    challonge_ref=(
                        tournament_challonge_refs.get(encounter.tournament_id)
                        if tournament_challonge_refs is not None
                        else None
                    ),
                )
                if tournament_cache is not None:
                    tournament_cache[encounter.tournament_id] = tournament
        if "teams" in entities or "home_team" in entities:
            teams_entities = (
                utils.prepare_entities(entities, "teams")
                if "teams" in entities
                else utils.prepare_entities(entities, "home_team")
            )
            if encounter.home_team is not None:
                home_team = await self._cached_team_read(session, encounter.home_team, teams_entities, team_cache)
        if "teams" in entities or "away_team" in entities:
            teams_entities = (
                utils.prepare_entities(entities, "teams")
                if "teams" in entities
                else utils.prepare_entities(entities, "away_team")
            )
            if encounter.away_team is not None:
                away_team = await self._cached_team_read(session, encounter.away_team, teams_entities, team_cache)
        if "matches" in entities:
            matches_read = [
                await self.to_pydantic_match(
                    session,
                    match,
                    utils.prepare_entities(entities, "matches"),
                    team_cache=team_cache,
                    tournament_cache=tournament_cache,
                )
                for match in encounter.matches
            ]
            # Same entity switch as `matches`: the encounter read carries both
            # what the tournament DECIDED per position (games) and what a parsed
            # log OBSERVED (matches), so a position can be named before any log
            # exists. Cancelled positions are history, not the live series.
            games_read = [
                schemas.EncounterGameRead(
                    id=game.id,
                    position=game.position,
                    map_id=game.map_id,
                    map=map_to_read(game.map, []) if game.map is not None else None,
                    state=game.state.value,
                    accepted_home_score=game.accepted_home_score,
                    accepted_away_score=game.accepted_away_score,
                    result_source=game.result_source.value if game.result_source is not None else None,
                    result_version=game.result_version,
                    confirmed_at=game.confirmed_at,
                )
                for game in sorted(encounter.games, key=lambda game: (game.position, game.id or 0))
                if game.state != EncounterGameState.CANCELLED
            ]

        encounter_dict = encounter.to_dict()
        # ``challonge_id`` (a bracket key) is DERIVED from challonge_match_mapping, not
        # read from the deprecated ``encounter.challonge_id`` column. Always set it so
        # the value survives the column being dropped; ``None`` when not prefetched.
        encounter_dict["challonge_id"] = (
            challonge_match_ids.get(encounter.id) if challonge_match_ids is not None else None
        )
        # ``has_logs`` is a ``column_property`` (derived EXISTS over ``matches.match``,
        # see ``shared/models/matches/match.py``), not a real column on
        # ``__table__`` -- ``to_dict()`` only walks ``__table__.columns`` and
        # silently drops it. Same footgun ``test_team_read_column_parity.py``
        # guards for ``Team.avg_sr``/``total_sr``.
        encounter_dict["has_logs"] = encounter.has_logs

        return schemas.EncounterRead(
            **encounter_dict,
            games=games_read,
            score=schemas.Score(home=encounter.home_score, away=encounter.away_score),
            stage=stage,
            stage_item=stage_item,
            tournament=tournament,
            home_team=home_team,
            away_team=away_team,
            matches=matches_read,
            sources=[
                schemas.EncounterSlotSourceRead(encounter_id=source.encounter_id, role=source.role, slot=source.slot)
                for source in (slot_sources or {}).get(encounter.id, ())
            ],
        )

    async def _cached_team_read(
        self,
        session: AsyncSession,
        team: models.Team,
        entities: list[str],
        team_cache: dict[int, schemas.TeamRead] | None,
    ) -> schemas.TeamRead:
        if team_cache is not None and team.id in team_cache:
            return team_cache[team.id]
        read = await self.teams.to_pydantic(session, team, entities)
        if team_cache is not None:
            team_cache[team.id] = read
        return read

    async def to_pydantic_match(
        self,
        session: AsyncSession,
        match: models.Match,
        entities: list[str],
        *,
        team_cache: dict[int, schemas.TeamRead] | None = None,
        tournament_cache: dict[int, schemas.TournamentRead] | None = None,
    ) -> schemas.MatchRead:
        """
        Converts a Match model instance to a Pydantic schema (MatchRead), including related entities.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            match (models.Match): The Match model instance to convert.
            entities (list[str]): A list of related entities to include (e.g., ["teams", "map"]).

        Returns:
            schemas.MatchRead: The Pydantic schema representing the match.
        """
        home_team: schemas.TeamRead | None = None
        away_team: schemas.TeamRead | None = None
        encounter: schemas.EncounterRead | None = None
        map_read: schemas.MapRead | None = None

        if "teams" in entities or "home_team" in entities:
            teams_entities = (
                utils.prepare_entities(entities, "teams")
                if "teams" in entities
                else utils.prepare_entities(entities, "home_team")
            )
            if match.home_team is not None:
                home_team = await self._cached_team_read(session, match.home_team, teams_entities, team_cache)
        if "teams" in entities or "away_team" in entities:
            teams_entities = (
                utils.prepare_entities(entities, "teams")
                if "teams" in entities
                else utils.prepare_entities(entities, "away_team")
            )
            if match.away_team is not None:
                away_team = await self._cached_team_read(session, match.away_team, teams_entities, team_cache)
        if "encounter" in entities:
            encounter = await self.to_pydantic(
                session,
                match.encounter,
                utils.prepare_entities(entities, "encounter"),
                tournament_cache=tournament_cache,
                team_cache=team_cache,
            )
        if "map" in entities:
            map_read = map_to_read(match.map, utils.prepare_entities(entities, "map"))

        return schemas.MatchRead(
            **match.to_dict(),
            score=schemas.Score(home=match.home_score, away=match.away_score),
            home_team=home_team,
            away_team=away_team,
            encounter=encounter,
            map=map_read,
        )

    async def get_encounter(
        self, session: AsyncSession, encounter_id: int, entities: list[str]
    ) -> schemas.EncounterRead:
        """
        Retrieves an encounter by its ID and converts it to a Pydantic schema.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            encounter_id (int): The ID of the encounter to retrieve.
            entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).

        Returns:
            schemas.EncounterRead: The Pydantic schema representing the encounter.

        Raises:
            errors.ApiHTTPException: If the encounter is not found.
        """
        encounter = await self.encounters.get_encounter(session, encounter_id, entities)
        if not encounter:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Encounter with id {encounter_id} not found")],
            )
        challonge_match_ids = await resolve_encounter_challonge(session, [encounter.id])
        tournament_challonge_refs = await resolve_tournament_challonge(session, [encounter.tournament_id])
        return await self.to_pydantic(
            session,
            encounter,
            entities,
            challonge_match_ids=challonge_match_ids,
            tournament_challonge_refs=tournament_challonge_refs,
            slot_sources=await resolve_slot_sources(session, [encounter.id]),
        )

    @cache(
        ttl=config.settings.encounters_cache_ttl,
        key="encounters:{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:{params.entities}:{params.only_count}:{params.query}:{params.fields}:{params.stage_id}:{params.stage_item_id}:{params.best_of}:{params.status}:{params.has_logs}:{params.closeness_min}:{params.closeness_max}:{params.scope}:{viewer_auth_user_id}",
        prefix="fastapi:",
    )
    async def get_all_encounters(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> pagination.Paginated[schemas.EncounterRead]:
        """
        Retrieves a paginated list of encounters and converts them to Pydantic schemas.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            params (schemas.EncounterSearchParams): Search, pagination, and sorting parameters.
            workspace_id (int | None): Optional workspace ID to filter encounters.

        Returns:
            pagination.Paginated[schemas.EncounterRead]: A paginated list of Pydantic schemas representing the encounters.
        """
        encounters, total = await self.encounters.get_all_encounters(
            session,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
        )
        challonge_match_ids = await resolve_encounter_challonge(session, [encounter.id for encounter in encounters])
        tournament_challonge_refs = await resolve_tournament_challonge(
            session, [encounter.tournament_id for encounter in encounters]
        )
        slot_sources = await resolve_slot_sources(session, [encounter.id for encounter in encounters])
        tournament_cache: dict[int, schemas.TournamentRead] = {}
        team_cache: dict[int, schemas.TeamRead] = {}
        return pagination.Paginated(
            total=total,
            per_page=params.per_page,
            page=params.page,
            results=[
                await self.to_pydantic(
                    session,
                    encounter,
                    params.entities,
                    challonge_match_ids=challonge_match_ids,
                    tournament_challonge_refs=tournament_challonge_refs,
                    slot_sources=slot_sources,
                    tournament_cache=tournament_cache,
                    team_cache=team_cache,
                )
                for encounter in encounters
            ],
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
        saved_view = await self.encounters.upsert_saved_view(
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

    @cache(
        ttl=config.settings.encounters_cache_ttl,
        key="encounters_overview:{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:{params.entities}:{params.only_count}:{params.query}:{params.fields}:{params.stage_id}:{params.stage_item_id}:{params.best_of}:{params.status}:{params.has_logs}:{params.closeness_min}:{params.closeness_max}:{params.scope}:{viewer_auth_user_id}",
        prefix="fastapi:",
        # NB: no ``lock=True`` — cashews builds the herd-lock key WITHOUT the
        # ``prefix``, and this codebase routes backends purely by key prefix (no
        # default backend), so the lock raises NotConfiguredError (same bug class
        # as lesson_cashews_prefixless_delete_match). TTL rollover herds are
        # mitigated by the FILTER-consolidated aggregate query instead.
    )
    async def get_encounters_overview(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> schemas.EncounterOverviewRead:
        data = await self.encounters.get_overview_data(
            session,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
        )
        total = data["total"]
        with_logs_count = data["with_logs_count"]
        completed_series_count = data["completed_series_count"]
        sweep_count = data["sweep_count"]
        home_wins = data["home_wins"]
        away_wins = data["away_wins"]
        decided_count = home_wins + away_wins

        histogram_by_bucket = {
            int(bucket): int(count) for bucket, count in data["histogram_rows"] if bucket is not None
        }
        histogram = [
            schemas.EncounterHistogramBucketRead(
                label=f"{index * 10}-{(index + 1) * 10}%",
                start=index / 10,
                end=(index + 1) / 10,
                count=histogram_by_bucket.get(index, 0),
            )
            for index in range(10)
        ]

        featured_encounters = [*data["closest"], *data["upcoming"], *data["live"]]
        featured_challonge_match_ids = await resolve_encounter_challonge(
            session, [encounter.id for encounter in featured_encounters]
        )
        featured_tournament_challonge_refs = await resolve_tournament_challonge(
            session, [encounter.tournament_id for encounter in featured_encounters]
        )
        featured_entities = ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"]
        featured_tournament_cache: dict[int, schemas.TournamentRead] = {}
        featured_team_cache: dict[int, schemas.TeamRead] = {}

        return schemas.EncounterOverviewRead(
            kpis=schemas.EncounterKpiRead(
                total_encounters=total,
                recent_count=data["recent_count"],
                with_logs_count=with_logs_count,
                with_logs_pct=round((with_logs_count / total) * 100, 1) if total else 0,
                avg_closeness=round(data["avg_closeness"] * 100, 1) if data["avg_closeness"] is not None else None,
                live_now_count=data["live_now_count"],
                upcoming_count=data["upcoming_count"],
            ),
            preset_counts=data["preset_counts"],
            closeness_histogram=histogram,
            score_heatmap=[
                schemas.EncounterScoreHeatmapCellRead(home=int(home), away=int(away), count=int(count))
                for home, away, count in data["score_rows"]
            ],
            stage_split=[
                schemas.EncounterStageSplitRead(
                    name=str(name),
                    count=int(count),
                    pct=round((int(count) / total) * 100, 1) if total else 0,
                )
                for name, count in data["stage_rows"]
            ],
            featured=schemas.EncounterFeaturedRead(
                closest=[
                    await self.to_pydantic(
                        session,
                        encounter,
                        featured_entities,
                        challonge_match_ids=featured_challonge_match_ids,
                        tournament_challonge_refs=featured_tournament_challonge_refs,
                        tournament_cache=featured_tournament_cache,
                        team_cache=featured_team_cache,
                    )
                    for encounter in data["closest"]
                ],
                upcoming=[
                    await self.to_pydantic(
                        session,
                        encounter,
                        featured_entities,
                        challonge_match_ids=featured_challonge_match_ids,
                        tournament_challonge_refs=featured_tournament_challonge_refs,
                        tournament_cache=featured_tournament_cache,
                        team_cache=featured_team_cache,
                    )
                    for encounter in data["upcoming"]
                ],
                live=[
                    await self.to_pydantic(
                        session,
                        encounter,
                        featured_entities,
                        challonge_match_ids=featured_challonge_match_ids,
                        tournament_challonge_refs=featured_tournament_challonge_refs,
                        tournament_cache=featured_tournament_cache,
                        team_cache=featured_team_cache,
                    )
                    for encounter in data["live"]
                ],
            ),
            hot_maps=[
                schemas.EncounterMapMetricRead(name=str(name), count=int(count)) for name, count in data["hot_map_rows"]
            ],
            pulse=schemas.EncounterPulseRead(
                avg_series_seconds=data["avg_series_seconds"],
                completed_series_count=completed_series_count,
                sweep_rate=round((sweep_count / completed_series_count) * 100, 1) if completed_series_count else 0,
                sweep_count=sweep_count,
                went_distance_count=data["went_distance_count"],
                reverse_sweep_rate=0,
                most_decisive_map=str(data["hot_map_rows"][0][0]) if data["hot_map_rows"] else None,
            ),
            side_balance=schemas.EncounterSideBalanceRead(
                home_wins=home_wins,
                away_wins=away_wins,
                home_win_pct=round((home_wins / decided_count) * 100, 1) if decided_count else 0,
                away_win_pct=round((away_wins / decided_count) * 100, 1) if decided_count else 0,
            ),
        )

    async def get_all_matches(
        self, session: AsyncSession, params: schemas.MatchSearchParams, workspace_id: int | None = None
    ) -> pagination.Paginated[schemas.MatchRead]:
        """
        Retrieves a paginated list of matches and converts them to Pydantic schemas.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            params (schemas.MatchSearchParams): Search, pagination, and sorting parameters.
            workspace_id (int | None): Optional workspace ID to filter matches by workspace.

        Returns:
            pagination.Paginated[schemas.MatchRead]: A paginated list of Pydantic schemas representing the matches.
        """
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
        """
        Retrieves a match by its ID and converts it to a Pydantic schema.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            match_id (int): The ID of the match to retrieve.
            entities (list[str]): A list of related entities to include (e.g., ["teams", "map"]).

        Returns:
            schemas.MatchRead: The Pydantic schema representing the match.

        Raises:
            errors.ApiHTTPException: If the match is not found.
        """
        match = await self.encounters.get_match(session, match_id, entities, workspace_id=workspace_id)
        if not match:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Match with id {match_id} not found")],
            )
        return await self.to_pydantic_match(session, match, entities)

    @cache(
        ttl=config.settings.match_cache_ttl,
        # No tournament_id in the args, so this key can't participate in the
        # targeted invalidation patterns — staleness is bounded by the short TTL.
        key="match_stats:{match_id}:{entities}:{workspace_id}",
        prefix="fastapi:",
    )
    async def get_match_with_stats(
        self,
        session: AsyncSession,
        match_id: int,
        entities: list[str],
        workspace_id: int | None = None,
    ) -> schemas.MatchReadWithStats:
        """
        Retrieves a match by its ID and converts it to a Pydantic schema with detailed statistics.

        Parameters:
            session (AsyncSession): The SQLAlchemy async session.
            match_id (int): The ID of the match to retrieve.
            entities (list[str]): A list of related entities to include (e.g., ["teams", "map"]).

        Returns:
            schemas.MatchReadWithStats: The Pydantic schema representing the match with detailed statistics.

        Raises:
            errors.ApiHTTPException: If the match is not found.
        """
        if "teams" not in entities:
            entities.append("teams")
        if "teams.players" not in entities:
            entities.append("teams.players")
        match = await self.get_match(session, match_id, entities, workspace_id=workspace_id)
        max_round: int = 0
        home_ids = [player.user_id for player in match.home_team.players]
        away_ids = [player.user_id for player in match.away_team.players]
        # One batched pair of aggregate queries for the whole roster instead of
        # 2 queries per player (this is the hottest public read — the match page).
        all_stats = await self.encounters.get_match_stats_for_users(session, match.id, [*home_ids, *away_ids])
        home_team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {}
        away_team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {}
        for user_id in home_ids:
            player_data = all_stats[user_id]
            home_team_stats[user_id] = player_data
            max_round = max(max_round, max(player_data[0].keys()) if player_data[0] else 0)
        for user_id in away_ids:
            player_data = all_stats[user_id]
            away_team_stats[user_id] = player_data
            max_round = max(max_round, max(player_data[0].keys()) if player_data[0] else 0)

        home_team = create_team_with_match_stats(match.home_team, home_team_stats)
        away_team = create_team_with_match_stats(match.away_team, away_team_stats)
        return schemas.MatchReadWithStats(
            **match.model_dump(exclude={"home_team", "away_team"}),
            rounds=max_round,
            home_team=home_team,
            away_team=away_team,
        )

    @cache(
        ttl=config.settings.match_cache_ttl,
        key="match_kill_feed:{match_id}:{workspace_id}",
        prefix="fastapi:",
    )
    async def get_match_kill_feed(
        self,
        session: AsyncSession,
        match_id: int,
        workspace_id: int | None = None,
    ) -> schemas.MatchKillFeedRead:
        """Kill feed + timeline events for a match as a chronological read schema.

        Validates the match exists within the (optional) workspace scope — mirrors
        ``get_match_with_stats`` so kill data can't cross workspace boundaries — then
        maps the raw joined rows to the typed read. Immutable once parsed, so it
        reuses the short match cache TTL.
        """
        # 404s if missing / out of workspace scope
        await self.get_match(session, match_id, [], workspace_id=workspace_id)

        kill_rows, event_rows = await self.encounters.get_match_kill_feed(session, match_id)

        kills = [
            schemas.KillFeedEntry(
                time=kf.time,
                round=kf.round,
                fight=kf.fight,
                ability=kf.ability.value if kf.ability is not None else None,
                damage=kf.damage,
                is_critical_hit=kf.is_critical_hit,
                is_environmental=kf.is_environmental,
                killer_user_id=kf.killer_id,
                killer_team_id=kf.killer_team_id,
                killer_hero=schemas.HeroRead.model_validate(killer_hero, from_attributes=True),
                victim_user_id=kf.victim_id,
                victim_team_id=kf.victim_team_id,
                victim_hero=schemas.HeroRead.model_validate(victim_hero, from_attributes=True),
            )
            for kf, killer_hero, victim_hero in kill_rows
        ]

        events = [
            schemas.MatchTimelineEvent(
                time=ev.time,
                round=ev.round,
                name=ev.name.value,
                user_id=ev.user_id,
                team_id=ev.team_id,
                hero=schemas.HeroRead.model_validate(hero, from_attributes=True) if hero is not None else None,
                related_user_id=ev.related_user_id,
                related_team_id=ev.related_team_id,
            )
            for ev, hero in event_rows
        ]

        return schemas.MatchKillFeedRead(match_id=match_id, kills=kills, events=events)


flows_service = EncounterFlowsService()
