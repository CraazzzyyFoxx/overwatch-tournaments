import typing
from collections import defaultdict

import sqlalchemy as sa
from shared.services.tournament_utils import sort_bracket_matches
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import utils
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows

from . import service


def sort_matches(
    matches: typing.Sequence[schemas.EncounterSummaryRead],
) -> list[schemas.EncounterSummaryRead]:
    """Phase E: delegate to shared utility (removes drift from parser-service)."""
    return sort_bracket_matches(matches)


def _entity_requested(entities: list[str], entity: str) -> bool:
    return entity in entities or any(item.startswith(f"{entity}.") for item in entities)


def _loaded_relationship(model: typing.Any, name: str) -> typing.Any | None:
    if name in sa.inspect(model).unloaded:
        return None
    return getattr(model, name)


def _history_by_team(encounters: typing.Sequence[models.Encounter]) -> dict[int, list[models.Encounter]]:
    histories: defaultdict[int, list[models.Encounter]] = defaultdict(list)
    for encounter in encounters:
        if encounter.home_team_id is not None:
            histories[encounter.home_team_id].append(encounter)
        if encounter.away_team_id is not None:
            histories[encounter.away_team_id].append(encounter)
    return dict(histories)


def _history_for_standing(
    standing: models.Standing,
    encounters: typing.Sequence[models.Encounter],
) -> list[schemas.EncounterSummaryRead]:
    return [
        schemas.EncounterSummaryRead(
            **encounter.to_dict(),
            score=schemas.Score(home=encounter.home_score, away=encounter.away_score),
        )
        for encounter in encounters
        if encounter.stage_id == standing.stage_id
        and (standing.stage_item_id is None or encounter.stage_item_id == standing.stage_item_id)
    ]


async def to_pydantic(
    session: AsyncSession,
    standing: models.Standing,
    entities: list[str],
    *,
    histories_by_team: dict[int, list[models.Encounter]] | None = None,
) -> schemas.StandingRead:
    """
    Converts a Standing model instance to a Pydantic schema (StandingRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        standing (models.Standing): The Standing model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["team", "group", "tournament", "matches_history"]).

    Returns:
        schemas.StandingRead: The Pydantic schema representing the standing.
    """
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
        team = await team_flows.to_pydantic(session, team_model, utils.prepare_entities(entities, "team"))
    if _entity_requested(entities, "stage") and stage_model is not None:
        stage = schemas.StageSummaryRead.model_validate(stage_model, from_attributes=True)
    if _entity_requested(entities, "stage_item") and stage_item_model is not None:
        stage_item = schemas.StageItemSummaryRead.model_validate(stage_item_model, from_attributes=True)
    if _entity_requested(entities, "tournament") and tournament_model is not None:
        tournament = await tournament_flows.to_pydantic(session, tournament_model, [])
    if "matches_history" in entities:
        if histories_by_team is None:
            histories_by_team = _history_by_team(
                await service.get_completed_match_history_by_tournament(session, standing.tournament_id)
            )
        matches_history = _history_for_standing(standing, histories_by_team.get(standing.team_id, []))

    # Expose the effective rule profile + tie-break order so clients can render
    # an accurate "ranked by …" legend without duplicating the engine defaults.
    source_rule_profile = service._rule_profile(stage_model) if stage_model is not None else None
    tiebreak_order = service._tiebreak_order(stage_model) if stage_model is not None else None

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
            "score_differential": standing.score_differential,
        },
        source_rule_profile=source_rule_profile,
        tiebreak_order=tiebreak_order,
        matches_history=sort_matches(matches_history),
    )


async def get_by_tournament(
    session: AsyncSession, tournament: models.Tournament, entities: list[str]
) -> list[schemas.StandingRead]:
    """
    Retrieves all standings for a specific tournament and converts them to Pydantic schemas.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament (models.Tournament): The Tournament model instance for which to retrieve standings.
        entities (list[str]): A list of related entities to include (e.g., ["team", "group", "tournament", "matches_history"]).

    Returns:
        list[schemas.StandingRead]: A list of Pydantic schemas representing the standings.
    """
    standings = await service.get_by_tournament(session, tournament, entities)
    histories_by_team = None
    if "matches_history" in entities:
        histories_by_team = _history_by_team(
            await service.get_completed_match_history_by_tournament(session, tournament.id)
        )
    return [
        await to_pydantic(session, standing, entities, histories_by_team=histories_by_team)
        for standing in standings
    ]
