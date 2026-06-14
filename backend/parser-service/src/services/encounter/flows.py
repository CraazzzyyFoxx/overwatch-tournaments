from loguru import logger
from shared.services.encounter_naming import build_encounter_name
from shared.services.stage_refs import resolve_stage_refs_from_group
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src import models, schemas
from src.core import enums, errors, utils
from src.services.challonge import sync as challonge_sync
from src.services.map import flows as map_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows
from src.services.tournament import service as tournament_service

from . import service


async def to_pydantic(
    session: AsyncSession, encounter: models.Encounter, entities: list[str]
) -> schemas.EncounterRead:
    stage: schemas.StageRead | None = None
    stage_item: schemas.StageItemRead | None = None
    tournament: schemas.TournamentRead | None = None
    home_team: schemas.TeamRead | None = None
    away_team: schemas.TeamRead | None = None
    matches_read: list[schemas.MatchRead] = []

    if "stage" in entities and encounter.stage is not None:
        stage = schemas.StageRead.model_validate(encounter.stage, from_attributes=True)
    if "stage_item" in entities and encounter.stage_item is not None:
        stage_item = schemas.StageItemRead.model_validate(
            encounter.stage_item, from_attributes=True
        )
    if "tournament" in entities and encounter.tournament is not None:
        tournament = await tournament_flows.to_pydantic(
            session,
            encounter.tournament,
            utils.prepare_entities(entities, "tournament"),
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

    return schemas.EncounterRead(
        **encounter.to_dict(),
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
    return await to_pydantic(session, encounter, entities)


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


async def _create_encounter_from_challonge(
    session: AsyncSession,
    tournament: models.Tournament,
    group_id: int,
    match: schemas.ChallongeMatch,
) -> models.Encounter | None:
    if match.state == "pending":
        logger.info(f"Encounter [name={match.id}] is pending. Skipping...")
        return None

    home_team = await team_flows.get_by_tournament_challonge_id(session, tournament.id, match.player1_id, [])
    away_team = await team_flows.get_by_tournament_challonge_id(session, tournament.id, match.player2_id, [])
    try:
        home_score, away_score = map(int, match.scores_csv.split("-"))
    except ValueError:
        home_score, away_score = 0, 0
    name = build_encounter_name(home_team.name, away_team.name)
    existed = await service.get_by_challonge_id(session, match.id, [])
    if existed:
        existed.home_score = home_score
        existed.away_score = away_score
        existed.status = enums.EncounterStatus(match.state if match.state != 'complete' else 'completed')
        # Self-heal stage refs for legacy encounters (stage_id/stage_item_id NULL)
        if existed.stage_id is None:
            refs = await resolve_stage_refs_from_group(
                session,
                tournament_id=tournament.id,
                tournament_group_id=group_id,
            )
            existed.stage_id = refs.stage_id
            existed.stage_item_id = refs.stage_item_id
        await session.commit()
        return existed
    match_db = await service.create(
        session,
        name=name,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        round=match.round,
        tournament=tournament,
        group_id=group_id,
        challonge_id=match.id,
        status=enums.EncounterStatus(match.state if match.state != 'complete' else 'completed'),
    )
    logger.info(
        f"Encounter [name={match_db.name}] created in tournament [id={tournament.id} number={tournament.number}]"
    )
    return match_db


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
