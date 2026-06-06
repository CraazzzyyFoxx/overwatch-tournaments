from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import utils
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows
from src.services.tournament import service as tournament_service

from . import service


async def to_pydantic(session: AsyncSession, standing: models.Standing, entities: list[str]) -> schemas.StandingRead:
    team: schemas.TeamRead | None = None
    stage: schemas.StageRead | None = None
    stage_item: schemas.StageItemRead | None = None
    tournament: schemas.TournamentRead | None = None

    if "team" in entities and standing.team is not None:
        team = await team_flows.to_pydantic(
            session, standing.team, utils.prepare_entities(entities, "team")
        )
    if "stage" in entities and standing.stage is not None:
        stage = schemas.StageRead.model_validate(standing.stage, from_attributes=True)
    if "stage_item" in entities and standing.stage_item is not None:
        stage_item = schemas.StageItemRead.model_validate(
            standing.stage_item, from_attributes=True
        )
    if "tournament" in entities:
        tournament = await tournament_flows.to_pydantic(session, standing.tournament, [])

    # Expose the effective rule profile + tie-break order so clients can render
    # an accurate "ranked by …" legend without duplicating the engine defaults.
    source_rule_profile = service._rule_profile(standing.stage) if standing.stage is not None else None
    tiebreak_order = service._tiebreak_order(standing.stage) if standing.stage is not None else None

    return schemas.StandingRead(
        **standing.to_dict(),
        team=team,
        stage=stage,
        stage_item=stage_item,
        tournament=tournament,
        ranking_context={
            "stage_type": standing.stage.stage_type.value if standing.stage else None,
            "stage_name": standing.stage.name if standing.stage else None,
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
    )


async def bulk_create_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    rewrite: bool = False,
) -> list[schemas.StandingRead]:
    if rewrite:
        await service.delete_by_tournament(session, tournament_id)

    tournament = await tournament_flows.get(session, tournament_id, ["groups", "stages"])
    if await service.get_by_tournament(session, tournament, []):
        logger.info(f"Standings for tournament {tournament_id} already exist. Skipping...")
        return []
    standings = await service.calculate_for_tournament(session, tournament)
    return [await to_pydantic(session, standing, ["team", "stage", "stage_item"]) for standing in standings]


async def recalculate_for_tournament(
    session: AsyncSession,
    tournament_id: int,
) -> list[schemas.StandingRead]:
    standings = await service.recalculate_for_tournament(session, tournament_id)
    return [
        await to_pydantic(session, standing, ["team", "stage", "stage_item"])
        for standing in standings
    ]


async def bulk_create(session: AsyncSession) -> None:
    for tournament in await tournament_service.get_all(session):
        await bulk_create_for_tournament(session, tournament.id)
