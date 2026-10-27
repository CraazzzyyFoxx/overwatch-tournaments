import typing
from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import utils
from shared.domain.tournament_utils import sort_bracket_matches
from shared.services.cache_generations import versioned
from src import schemas
from src.core import config
from src.services.encounter.flows import to_summary
from src.services.team.flows import flows_service as team_flows_service
from src.services.tournament.cache_resources import STANDINGS, tournament_generations
from src.services.tournament.flows import flows_service as tournament_flows_service

from . import service
from .service import StandingsService, standings_service


def sort_matches(
    matches: typing.Sequence[schemas.EncounterSummaryRead],
) -> list[schemas.EncounterSummaryRead]:
    """Sort bracket matches with the shared helper parser-service also uses."""
    return sort_bracket_matches(matches)


def _entity_requested(entities: list[str], entity: str) -> bool:
    return entity in entities or any(item.startswith(f"{entity}.") for item in entities)


def _loaded_relationship(model: typing.Any, name: str) -> typing.Any | None:
    if name in sa.inspect(model).unloaded:
        return None
    return getattr(model, name)


#: One completed encounter of the history, with the bracket position its scope
#: and round come from.
HistoryRow = tuple[models.Encounter, models.BracketEncounter]

#: The entities ``get_by_tournament`` honours: all its key keeps of the client's list (``canonical_entities``).
READ_ENTITIES = frozenset({"team", "stage", "stage_item", "tournament", "matches_history"})


class _StageFacts(typing.NamedTuple):
    """What every standing row of one stage reads off it."""

    read: schemas.StageSummaryRead | None
    rule_profile: str
    tiebreak_order: list[str]


def _history_by_team(encounters: typing.Sequence[HistoryRow]) -> dict[int, list[HistoryRow]]:
    """Index the history by the teams that actually sat in each encounter.

    Off the participations, not two team columns: a lobby of four belongs in
    four teams' histories, and a seat that changed hands belongs to whoever
    holds it now.
    """
    histories: defaultdict[int, list[HistoryRow]] = defaultdict(list)
    for encounter, position in encounters:
        for seat in encounter.teams:
            if seat.active and seat.team_id is not None:
                histories[seat.team_id].append((encounter, position))
    return dict(histories)


def _history_for_standing(
    standing: models.Standing,
    encounters: typing.Sequence[HistoryRow],
) -> list[schemas.EncounterSummaryRead]:
    return [
        to_summary(encounter, position)
        for encounter, position in encounters
        if position.stage_id == standing.stage_id
        and (standing.stage_item_id is None or position.stage_item_id == standing.stage_item_id)
    ]


class StandingsFlowsService:
    def __init__(self, *, standings: StandingsService = standings_service) -> None:
        self.standings = standings

    async def to_pydantic(
        self,
        session: AsyncSession,
        standing: models.Standing,
        entities: list[str],
        *,
        histories_by_team: dict[int, list[HistoryRow]] | None = None,
        tournament_cache: schemas.TournamentRead | None = None,
        team_cache: dict[int, schemas.TeamRead] | None = None,
        stage_cache: dict[int, _StageFacts] | None = None,
    ) -> schemas.StandingRead:
        """Convert a Standing to ``StandingRead`` with the requested related ``entities``."""
        team: schemas.TeamRead | None = None
        stage: schemas.StageSummaryRead | None = None
        stage_item: schemas.StageItemSummaryRead | None = None
        tournament: schemas.TournamentRead | None = None
        matches_history: list[schemas.EncounterSummaryRead] = []
        team_model = typing.cast(models.Team | None, _loaded_relationship(standing, "team"))
        stage_model = typing.cast(models.Stage | None, _loaded_relationship(standing, "stage"))
        stage_item_model = typing.cast(models.StageItem | None, _loaded_relationship(standing, "stage_item"))
        tournament_model = typing.cast(models.Tournament | None, _loaded_relationship(standing, "tournament"))

        if _entity_requested(entities, "team") and team_model is not None:
            if team_cache is not None and team_model.id in team_cache:
                team = team_cache[team_model.id]
            else:
                team = await team_flows_service.to_pydantic(
                    session, team_model, utils.prepare_entities(entities, "team")
                )
                if team_cache is not None:
                    team_cache[team_model.id] = team
        # A stage's read and its effective rules are the same for each of its rows: built once per stage.
        source_rule_profile = tiebreak_order = None
        if stage_model is not None:
            facts = stage_cache.get(stage_model.id) if stage_cache is not None else None
            if facts is None:
                facts = _StageFacts(
                    schemas.StageSummaryRead.model_validate(stage_model, from_attributes=True)
                    if _entity_requested(entities, "stage")
                    else None,
                    service._rule_profile(stage_model),
                    service._tiebreak_order(stage_model),
                )
                if stage_cache is not None:
                    stage_cache[stage_model.id] = facts
            stage, source_rule_profile, tiebreak_order = facts
        if _entity_requested(entities, "stage_item") and stage_item_model is not None:
            stage_item = schemas.StageItemSummaryRead.model_validate(stage_item_model, from_attributes=True)
        if _entity_requested(entities, "tournament") and tournament_model is not None:
            # Every standing in one get_by_tournament call shares the SAME tournament
            # row — recomputing its (entities=[]) pydantic form per standing is pure
            # CPU waste, not a query, but still O(standings) work for one answer.
            tournament = (
                tournament_cache
                if tournament_cache is not None
                else await tournament_flows_service.to_pydantic(session, tournament_model, [])
            )
        if "matches_history" in entities:
            if histories_by_team is None:
                histories_by_team = _history_by_team(
                    await self.standings.get_completed_match_history_by_tournament(session, standing.tournament_id)
                )
            matches_history = _history_for_standing(standing, histories_by_team.get(standing.team_id, []))

        return schemas.StandingRead(
            **standing.to_dict(),
            team=team,
            stage=stage,
            stage_item=stage_item,
            tournament=tournament,
            ranking_context={
                "stage_type": stage_model.stage_type.value if stage_model else None,
                "stage_name": stage_model.name if stage_model else None,
                "stage_item_name": stage_item_model.name if stage_item_model else None,
            },
            tb_metrics={
                "points": standing.points,
                "match_wins": standing.win,
                "head_to_head": standing.tb,
                "median_buchholz": standing.buchholz,
                "buchholz": standing.full_buchholz,
                "score_differential": standing.score_differential,
            },
            source_rule_profile=source_rule_profile,
            tiebreak_order=tiebreak_order,
            matches_history=sort_matches(matches_history),
        )

    # Values are the dumped wire dicts (``v2``), not pickled ``StandingRead``s: a hit is then a plain unpickle, and
    # since cashews hands a value back unvalidated, a wire change bumps the version.
    @versioned(
        generations=tournament_generations("{tournament_id}", STANDINGS),
        ttl=config.settings.standings_cache_ttl,
        key="standings_by_tournament:v2:{tournament_id}:{entities}",
        prefix="fastapi:",
    )
    async def get_by_tournament(
        self, session: AsyncSession, tournament_id: int, entities: list[str]
    ) -> list[dict[str, typing.Any]]:
        """All standings of a tournament as ``StandingRead`` wire dicts (``exclude_none``), with the requested
        ``entities`` (the key's too: pass them through ``canonical_entities(..., READ_ENTITIES)``).

        Standings rows change on a recalculation and on a stage restructure; the
        embedded ``matches_history`` also moves whenever an encounter does. Every
        one of those publishes a resource in ``STANDINGS``, whose generation is
        part of this key, so a plain TTL cache here is safe.
        """
        standings = await self.standings.get_by_tournament(session, tournament_id, entities)
        histories_by_team = None
        if "matches_history" in entities:
            histories_by_team = _history_by_team(
                await self.standings.get_completed_match_history_by_tournament(session, tournament_id)
            )
        # Every standing shares one tournament and often repeats a team and a stage
        # across rows — precompute/memoize instead of re-serializing per row.
        tournament_cache = None
        if _entity_requested(entities, "tournament"):
            tournament_model = await tournament_flows_service.get(session, tournament_id, [])
            tournament_cache = await tournament_flows_service.to_pydantic(session, tournament_model, [])
        team_cache: dict[int, schemas.TeamRead] = {}
        stage_cache: dict[int, _StageFacts] = {}
        return [
            (
                await self.to_pydantic(
                    session,
                    standing,
                    entities,
                    histories_by_team=histories_by_team,
                    tournament_cache=tournament_cache,
                    team_cache=team_cache,
                    stage_cache=stage_cache,
                )
            ).model_dump(mode="json", exclude_none=True)
            for standing in standings
        ]


flows_service = StandingsFlowsService()
