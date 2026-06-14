import typing

import sqlalchemy as sa
from loguru import logger
from shared.services.stage_refs import (
    StageRefs,
    resolve_stage_refs_from_group,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models
from src.core import enums, utils
from src.services.map import service as map_service
from src.services.team import service as team_service
from src.services.tournament import service as tournament_service


def encounter_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities = []
    if "tournament" in in_entities:
        tournament_entity = utils.join_entity(child, models.Encounter.tournament)
        entities.append(tournament_entity)
        entities.extend(
            tournament_service.tournament_entities(utils.prepare_entities(in_entities, "tournament"), tournament_entity)
        )
    if "tournament_group" in in_entities:
        entities.append(utils.join_entity(child, models.Encounter.tournament_group))
    if "group" in in_entities:
        entities.append(utils.join_entity(child, models.Encounter.tournament_group))
    if "teams" in in_entities:
        home_team_entity = utils.join_entity(child, models.Encounter.home_team)
        away_team_entity = utils.join_entity(child, models.Encounter.away_team)
        entities.append(home_team_entity)
        entities.append(away_team_entity)
        entities.extend(team_service.team_entities(utils.prepare_entities(in_entities, "teams"), home_team_entity))
        entities.extend(team_service.team_entities(utils.prepare_entities(in_entities, "teams"), away_team_entity))
    if "home_team" in in_entities:
        home_team_entity = utils.join_entity(child, models.Encounter.home_team)
        entities.append(home_team_entity)
        entities.extend(
            team_service.team_entities(
                utils.prepare_entities(in_entities, "home_team"),
                home_team_entity,
            )
        )
    if "away_team" in in_entities:
        away_team_entity = utils.join_entity(child, models.Encounter.away_team)
        entities.append(away_team_entity)
        entities.extend(
            team_service.team_entities(
                utils.prepare_entities(in_entities, "away_team"),
                away_team_entity,
            )
        )
    if "stage" in in_entities:
        stage_entity = utils.join_entity(child, models.Encounter.stage)
        stage_items_entity = utils.join_entity(stage_entity, models.Stage.items)
        entities.append(stage_entity)
        entities.append(stage_items_entity)
        entities.append(utils.join_entity(stage_items_entity, models.StageItem.inputs))
    if "stage_item" in in_entities:
        stage_item_entity = utils.join_entity(child, models.Encounter.stage_item)
        entities.append(stage_item_entity)
        entities.append(utils.join_entity(stage_item_entity, models.StageItem.inputs))
    if "matches" in in_entities:
        matches_entity = utils.join_entity(child, models.Encounter.matches)
        entities.append(matches_entity)
        entities.extend(match_entities(utils.prepare_entities(in_entities, "matches"), matches_entity))

    return entities


def match_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities = []

    if "teams" in in_entities:
        home_team_entity = utils.join_entity(child, models.Match.home_team)
        away_team_entity = utils.join_entity(child, models.Match.away_team)
        entities.append(home_team_entity)
        entities.append(away_team_entity)
        entities.extend(team_service.team_entities(utils.prepare_entities(in_entities, "teams"), home_team_entity))
        entities.extend(team_service.team_entities(utils.prepare_entities(in_entities, "teams"), away_team_entity))
    if "home_team" in in_entities:
        home_team_entity = utils.join_entity(child, models.Match.home_team)
        entities.append(home_team_entity)
        entities.extend(
            team_service.team_entities(
                utils.prepare_entities(in_entities, "home_team"),
                home_team_entity,
            )
        )
    if "away_team" in in_entities:
        away_team_entity = utils.join_entity(child, models.Match.away_team)
        entities.append(away_team_entity)
        entities.extend(
            team_service.team_entities(
                utils.prepare_entities(in_entities, "away_team"),
                away_team_entity,
            )
        )
    if "encounter" in in_entities:
        entities.append(utils.join_entity(child, models.Match.encounter))
    if "map" in in_entities:
        map_entity = utils.join_entity(child, models.Match.map)
        entities.append(map_entity)
        entities.extend(map_service.map_entities(utils.prepare_entities(in_entities, "map"), map_entity))
    return entities


async def get_encounter(session: AsyncSession, id: int, entities: list[str]) -> models.Encounter | None:
    query = sa.select(models.Encounter).options(*encounter_entities(entities)).where(sa.and_(models.Encounter.id == id))
    result = await session.execute(query)
    return result.unique().scalars().first()


def join_encounter_entities(query: sa.Select, in_entities: list[str]) -> sa.Select:
    if "tournament" in in_entities:
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
    if "group" in in_entities:
        query = query.join(
            models.TournamentGroup,
            models.Encounter.tournament_group_id == models.TournamentGroup.id,
        )

    return query


async def get_by_challonge_id(session: AsyncSession, challonge_id: int, entities: list[str]) -> models.Encounter | None:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(sa.and_(models.Encounter.challonge_id == challonge_id))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_tournament_group_id(
    session: AsyncSession, tournament_id: int, group_id: int, entities: list[str]
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.and_(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.tournament_group_id == group_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_by_stage_id(
    session: AsyncSession, tournament_id: int, stage_id: int, entities: list[str]
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.and_(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.stage_id == stage_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_by_stage_item_id(
    session: AsyncSession,
    tournament_id: int,
    stage_item_id: int,
    entities: list[str],
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.and_(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.stage_item_id == stage_item_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_by_name_group_id(
    session: AsyncSession, name: str, group_id: int, entities: list[str]
) -> models.Encounter | None:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.and_(
                models.Encounter.name == name,
                models.Encounter.tournament_group_id == group_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_match_by_encounter_and_map(
    session: AsyncSession, encounter_id: int, map_id: int, entities: list[str]
) -> models.Match | None:
    query = (
        sa.select(models.Match)
        .where(sa.and_(models.Match.encounter_id == encounter_id, models.Match.map_id == map_id))
        .options(*match_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_teams(
    session: AsyncSession,
    home_team_id: int,
    away_team_id: int,
    entities: list[str],
    *,
    has_closeness: bool | None = False,
) -> models.Encounter | None:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.or_(
                sa.and_(
                    models.Encounter.home_team_id == home_team_id,
                    models.Encounter.away_team_id == away_team_id,
                ),
                sa.and_(
                    models.Encounter.home_team_id == away_team_id,
                    models.Encounter.away_team_id == home_team_id,
                ),
            )
        )
    )

    if isinstance(has_closeness, bool):
        if has_closeness:
            query = query.where(models.Encounter.closeness.isnot(None))
        else:
            query = query.where(models.Encounter.closeness.is_(None))

    result = await session.execute(query)
    return result.unique().scalars().first()


def get_by_teams_sync(
    session: Session, home_team_id: int, away_team_id: int, entities: list[str]
) -> models.Encounter | None:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.or_(
                sa.and_(
                    models.Encounter.home_team_id == home_team_id,
                    models.Encounter.away_team_id == away_team_id,
                ),
                sa.and_(
                    models.Encounter.home_team_id == away_team_id,
                    models.Encounter.away_team_id == home_team_id,
                ),
            )
        )
    )
    result = session.execute(query)
    return result.unique().scalars().first()


async def get_by_team(session: AsyncSession, team_id: int, entities: list[str]) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(
            sa.or_(
                models.Encounter.home_team_id == team_id,
                models.Encounter.away_team_id == team_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_encounter_by_names(
    session: AsyncSession,
    tournament: models.Tournament,
    home_team: models.Team,
    away_team: models.Team,
) -> models.Encounter:
    query = sa.select(models.Encounter).where(
        sa.and_(
            models.Encounter.tournament_id == tournament.id,
            models.Encounter.home_team_id == home_team.id,
            models.Encounter.away_team_id == away_team.id,
        )
    )
    result = await session.execute(query)
    return result.scalars().one()


async def get_encounters_by_tournament(
    session: AsyncSession, tournament_id: int, entities: list[str]
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(*encounter_entities(entities))
        .where(models.Encounter.tournament_id == tournament_id)
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def create(
    session: AsyncSession,
    *,
    name: str,
    home_team: models.Team | None,
    away_team: models.Team | None,
    home_score: int,
    away_score: int,
    round: int,
    tournament: models.Tournament,
    group_id: int | None,
    status: enums.EncounterStatus,
    challonge_id: int | None = None,
    has_logs: bool = False,
    stage_id: int | None = None,
    stage_item_id: int | None = None,
) -> models.Encounter:
    """Create a new encounter.

    stage_id / stage_item_id are resolved from ``group_id`` via
    :func:`shared.services.stage_refs.resolve_stage_refs_from_group` when not
    supplied explicitly, so legacy flows (Challonge sync, parser) no longer
    produce encounters with NULL stage refs.
    """
    refs: StageRefs = await resolve_stage_refs_from_group(
        session,
        tournament_id=tournament.id,
        tournament_group_id=group_id,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
    )

    encounter = models.Encounter(
        name=name,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        round=round,
        tournament_id=tournament.id,
        tournament_group_id=group_id,
        stage_id=refs.stage_id,
        stage_item_id=refs.stage_item_id,
        challonge_id=challonge_id,
        status=status,
        has_logs=has_logs,
    )
    session.add(encounter)
    await session.commit()
    return encounter


async def update(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    name: str | None = None,
    home_team_id: int | None = None,
    away_team_id: int | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    round: int | None = None,
    tournament_id: int | None = None,
    group_id: int | None = None,
    challonge_id: int | None = None,
    status: enums.EncounterStatus | None = None,
    has_logs: bool | None = None,
) -> models.Encounter:
    encounter.name = name or encounter.name
    encounter.home_team_id = home_team_id or encounter.home_team_id
    encounter.away_team_id = away_team_id or encounter.away_team_id
    encounter.home_score = home_score or encounter.home_score
    encounter.away_score = away_score or encounter.away_score
    encounter.round = round or encounter.round
    encounter.tournament_id = tournament_id or encounter.tournament_id
    encounter.challonge_id = challonge_id or encounter.challonge_id
    encounter.status = status or encounter.status
    if has_logs is not None:
        encounter.has_logs = has_logs

    if group_id is not None and group_id != encounter.tournament_group_id:
        encounter.tournament_group_id = group_id
        # При смене группы — пересчитать stage refs, чтобы сетка и админка
        # не расходились.
        refs = await resolve_stage_refs_from_group(
            session,
            tournament_id=encounter.tournament_id,
            tournament_group_id=group_id,
            stage_id=encounter.stage_id,
            stage_item_id=encounter.stage_item_id,
        )
        encounter.stage_id = refs.stage_id
        encounter.stage_item_id = refs.stage_item_id
    elif encounter.stage_id is None and encounter.tournament_group_id is not None:
        # Self-heal для legacy-encounters, где stage_id/stage_item_id NULL:
        # резолвим при любом update.
        refs = await resolve_stage_refs_from_group(
            session,
            tournament_id=encounter.tournament_id,
            tournament_group_id=encounter.tournament_group_id,
        )
        encounter.stage_id = refs.stage_id
        encounter.stage_item_id = refs.stage_item_id

    await session.commit()
    return encounter


async def update_encounter_logs(
    session: AsyncSession,
    encounter_id: int,
    *,
    has_logs: bool,
    commit: bool = True,
) -> models.Encounter:
    result = await session.execute(
        sa.select(models.Encounter).where(models.Encounter.id == encounter_id).with_for_update(nowait=False)
    )
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise ValueError(f"Encounter {encounter_id} not found")

    encounter.has_logs = has_logs
    if commit:
        await session.commit()
    else:
        await session.flush()
    return encounter


async def update_encounter_result(
    session: AsyncSession,
    encounter_id: int,
    *,
    home_score: int | None = None,
    away_score: int | None = None,
    status: enums.EncounterStatus | None = None,
    result_status: enums.EncounterResultStatus | None = None,
) -> models.Encounter:
    result = await session.execute(
        sa.select(models.Encounter).where(models.Encounter.id == encounter_id).with_for_update(nowait=False)
    )
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise ValueError(f"Encounter {encounter_id} not found")

    if home_score is not None:
        encounter.home_score = home_score
    if away_score is not None:
        encounter.away_score = away_score
    if status is not None:
        encounter.status = status
    if result_status is not None:
        encounter.result_status = result_status

    await session.commit()
    return encounter


async def create_match(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    time: float,
    log_name: str,
    map: models.Map,
    home_team_id: int,
    away_team_id: int,
    home_score: int,
    away_score: int,
    commit: bool = True,
) -> models.Match:
    match = models.Match(
        time=time,
        log_name=log_name,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        encounter_id=encounter.id,
        map_id=map.id,
    )
    session.add(match)
    await session.flush()
    if commit:
        await session.commit()
    logger.info(
        f"Match created [home_team_id={home_team_id}, away_team_id={away_team_id}] for encounter {encounter.id}"
    )
    return match
