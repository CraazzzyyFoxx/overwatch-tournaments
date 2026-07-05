import typing

from loguru import logger
from shared.services.challonge_refs import (
    ChallongeRef,
    resolve_encounter_challonge,
    resolve_tournament_challonge,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src import models, schemas
from src.core import errors, utils
from src.services.challonge import sync as challonge_sync
from src.services.map import flows as map_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows
from src.services.tournament import service as tournament_service

from . import service


async def to_pydantic(
    session: AsyncSession,
    encounter: models.Encounter,
    entities: list[str],
    *,
    challonge_match_ids: typing.Mapping[int, int] | None = None,
    tournament_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None,
) -> schemas.EncounterRead:
    """Serialize an encounter.

    ``challonge_match_ids`` carries the KEPT ``challonge_id`` response field (a
    bracket key for the frontend) DERIVED from ``challonge_match_mapping`` (see
    ``shared.services.challonge_refs``) instead of the deprecated
    ``encounter.challonge_id`` column; ``tournament_challonge_refs`` does the same
    for the nested ``tournament``. Both default to ``None`` when not prefetched.
    """
    stage: schemas.StageRead | None = None
    stage_item: schemas.StageItemRead | None = None
    tournament: schemas.TournamentRead | None = None
    home_team: schemas.TeamRead | None = None
    away_team: schemas.TeamRead | None = None
    matches_read: list[schemas.MatchRead] = []

    if "stage" in entities and encounter.stage is not None:
        # Nested stage challonge is derived at the tournament read, not here —
        # override to None so the legacy ``stage`` columns are never read.
        stage = schemas.StageRead.model_validate(encounter.stage, from_attributes=True).model_copy(
            update={"challonge_id": None, "challonge_slug": None}
        )
    if "stage_item" in entities and encounter.stage_item is not None:
        stage_item = schemas.StageItemRead.model_validate(
            encounter.stage_item, from_attributes=True
        )
    if "tournament" in entities and encounter.tournament is not None:
        tournament = await tournament_flows.to_pydantic(
            session,
            encounter.tournament,
            utils.prepare_entities(entities, "tournament"),
            challonge_ref=(
                tournament_challonge_refs.get(encounter.tournament_id)
                if tournament_challonge_refs is not None
                else None
            ),
        )
    if "teams" in entities or "home_team" in entities:
        team_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "home_team")
        )
        home_team = await team_flows.to_pydantic(
            session, encounter.home_team, team_entities
        )
    if "teams" in entities or "away_team" in entities:
        team_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "away_team")
        )
        away_team = await team_flows.to_pydantic(
            session, encounter.away_team, team_entities
        )
    if "matches" in entities:
        matches_read = [
            await to_pydantic_match(
                session, match, utils.prepare_entities(entities, "matches")
            )
            for match in encounter.matches
        ]

    encounter_dict = encounter.to_dict()
    # ``challonge_id`` (a bracket key) is DERIVED from challonge_match_mapping, not
    # read from the deprecated ``encounter.challonge_id`` column. Always override so
    # the value survives the column being dropped; ``None`` when not prefetched.
    encounter_dict["challonge_id"] = (
        challonge_match_ids.get(encounter.id) if challonge_match_ids is not None else None
    )
    return schemas.EncounterRead(
        **encounter_dict,
        score=schemas.Score(home=encounter.home_score, away=encounter.away_score),
        stage=stage,
        stage_item=stage_item,
        tournament=tournament,
        home_team=home_team,
        away_team=away_team,
        matches=matches_read,
    )


async def to_pydantic_match(
    session: AsyncSession, match: models.Match, entities: list[str]
) -> schemas.MatchRead:
    home_team: schemas.TeamRead | None = None
    away_team: schemas.TeamRead | None = None
    encounter_read: schemas.EncounterRead | None = None
    map_read: schemas.MapRead | None = None

    if "teams" in entities or "home_team" in entities:
        team_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "home_team")
        )
        home_team = await team_flows.to_pydantic(session, match.home_team, team_entities)
    if "teams" in entities or "away_team" in entities:
        team_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "away_team")
        )
        away_team = await team_flows.to_pydantic(session, match.away_team, team_entities)
    if "encounter" in entities and match.encounter is not None:
        encounter_read = await to_pydantic(
            session, match.encounter, utils.prepare_entities(entities, "encounter")
        )
    if "map" in entities and match.map is not None:
        map_read = await map_flows.to_pydantic(
            session, match.map, utils.prepare_entities(entities, "map")
        )

    return schemas.MatchRead(
        **match.to_dict(),
        score=schemas.Score(home=match.home_score, away=match.away_score),
        home_team=home_team,
        away_team=away_team,
        encounter=encounter_read,
        map=map_read,
    )


async def get_encounter(
    session: AsyncSession, encounter_id: int, entities: list[str]
) -> schemas.EncounterRead:
    encounter = await service.get_encounter(session, encounter_id, entities)
    if not encounter:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found", msg=f"Encounter with id {encounter_id} not found"
                )
            ],
        )
    challonge_match_ids = await resolve_encounter_challonge(session, [encounter.id])
    tournament_challonge_refs = await resolve_tournament_challonge(session, [encounter.tournament_id])
    return await to_pydantic(
        session,
        encounter,
        entities,
        challonge_match_ids=challonge_match_ids,
        tournament_challonge_refs=tournament_challonge_refs,
    )


async def get_by_teams_ids(
    session: AsyncSession,
    home_team_id: int,
    away_team_id: int,
    entities: list[str],
    *,
    has_closeness: bool | None = None,
) -> models.Encounter:
    encounter = await service.get_by_teams(session, home_team_id, away_team_id, entities, has_closeness=has_closeness)
    if not encounter:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Encounter with teams [{home_team_id}, {away_team_id}] not found",
                )
            ],
        )
    return encounter


def get_by_teams_ids_sync(session: Session, home_team_id: int, away_team_id: int) -> models.Encounter:
    encounter = service.get_by_teams_sync(session, home_team_id, away_team_id, [])
    if not encounter:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Encounter with teams [{home_team_id}, {away_team_id}] not found",
                )
            ],
        )
    return encounter


async def bulk_create_for_tournament_from_challonge(
    session: AsyncSession,
    tournament_id: int,
    skip_finals: bool = False,
) -> dict:
    if skip_finals:
        logger.warning("skip_finals is ignored by unified Challonge import")
    return await challonge_sync.import_tournament(session, tournament_id)


async def bulk_create_for_from_challonge(session: AsyncSession) -> dict:
    tournaments = await tournament_service.get_all(session)
    totals = {
        "tournaments_synced": 0,
        "matches_synced": 0,
        "matches_created": 0,
        "matches_updated": 0,
        "matches_skipped": 0,
        "errors": 0,
    }
    for tournament in tournaments:
        if tournament.id == 4:
            continue  # In this tournament we have two brackets, but the first bracket is not finished.
            # Suz Playoffs filled manually
        result = await bulk_create_for_tournament_from_challonge(session, tournament.id)
        totals["tournaments_synced"] += 1
        if "error" in result:
            totals["errors"] += 1
            continue
        for key in (
            "matches_synced",
            "matches_created",
            "matches_updated",
            "matches_skipped",
            "errors",
        ):
            totals[key] += int(result.get(key, 0) or 0)
    return totals


async def create_match(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    time: int,
    map: models.Map,
    log_name: str,
    home_team_id: int,
    away_team_id: int,
    home_score: int,
    away_score: int,
) -> models.Match:
    match = await service.get_match_by_encounter_and_map(session, encounter.id, map.id, [])
    if match:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="already_exists",
                    msg=f"Match with encounter {encounter.id} and map {map.id} already exists",
                )
            ],
        )
    return await service.create_match(
        session,
        encounter=encounter,
        time=time,
        map=map,
        log_name=log_name,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
    )
