from datetime import date

from loguru import logger
from shared.services.division_grid_access import get_workspace_division_grid_version_id
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import errors
from src.services.challonge import service as challonge_service

from . import service


async def to_pydantic(
    session: AsyncSession, tournament: models.Tournament, entities: list[str]
) -> schemas.TournamentRead:
    stages: list[schemas.StageRead] = []
    if "stages" in entities:
        stages = [
            schemas.StageRead.model_validate(stage, from_attributes=True)
            for stage in sorted(tournament.stages, key=lambda item: item.order)
        ]
    return schemas.TournamentRead(
        id=tournament.id,
        workspace_id=tournament.workspace_id,
        start_date=tournament.start_date,
        end_date=tournament.end_date,
        number=tournament.number,
        is_league=tournament.is_league,
        is_finished=tournament.is_finished,
        status=tournament.status,
        name=tournament.name,
        description=tournament.description,
        challonge_id=tournament.challonge_id,
        challonge_slug=tournament.challonge_slug,
        registration_opens_at=tournament.registration_opens_at,
        registration_closes_at=tournament.registration_closes_at,
        check_in_opens_at=tournament.check_in_opens_at,
        check_in_closes_at=tournament.check_in_closes_at,
        win_points=tournament.win_points,
        draw_points=tournament.draw_points,
        loss_points=tournament.loss_points,
        division_grid_version_id=tournament.division_grid_version_id,
        division_grid_version=(
            schemas.DivisionGridVersionRead.model_validate(tournament.division_grid_version, from_attributes=True)
            if tournament.division_grid_version is not None
            else None
        ),
        stages=stages,
    )


async def to_pydantic_group(
    session: AsyncSession, group: models.TournamentGroup, entities: list[str]
) -> schemas.TournamentGroupRead:
    return schemas.TournamentGroupRead(
        id=group.id,
        name=group.name,
        is_groups=group.is_groups,
        challonge_id=group.challonge_id,
        challonge_slug=group.challonge_slug,
        description=group.description,
    )


async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Tournament:
    tournament = await service.get(session, id, entities)
    if tournament is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="tournament_not_found",
                    msg="Tournament with this id not found",
                )
            ],
        )
    return tournament


async def get_read(session: AsyncSession, id: int, entities: list[str]) -> schemas.TournamentRead:
    tournament = await get(session, id, entities)
    return await to_pydantic(session, tournament, entities)


async def get_by_number(session: AsyncSession, number: int, entities: list[str]) -> models.Tournament:
    tournament = await service.get_by_number(session, number, entities)
    if tournament is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="tournament_not_found",
                    msg="Tournament with this number not found",
                )
            ],
        )
    return tournament


async def get_by_number_and_league(
    session: AsyncSession, number: int, is_league: bool, entities: list[str]
) -> models.Tournament:
    tournament = await service.get_by_number_and_league(session, number, is_league, entities)
    if tournament is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="tournament_not_found",
                    msg="Tournament with this number not found",
                )
            ],
        )
    return tournament


async def get_by_name(session: AsyncSession, name: str, entities: list[str]) -> models.Tournament:
    tournament = await service.get_by_name(session, name, entities)
    if tournament is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="tournament_not_found",
                    msg="Tournament with this name not found",
                )
            ],
        )
    return tournament


def get_groups_from_matches(
    matches: list[schemas.ChallongeMatch],
) -> list[tuple[int, str]]:
    groups_ids: list[int] = []
    for match in matches:
        if match.group_id is None:
            continue
        if match.group_id not in groups_ids:
            groups_ids.append(match.group_id)

    groups: list[tuple[int, str]] = []
    for sym_index, group_id in enumerate(sorted(groups_ids), start=65):
        groups.append((group_id, chr(sym_index)))

    return groups


async def create_groups(
    session: AsyncSession,
    tournament: models.Tournament,
    challonge_tournament: schemas.ChallongeTournament,
) -> models.Tournament:
    matches = await challonge_service.fetch_matches(challonge_tournament.id)
    for match in matches:
        logger.info(match)
    groups = get_groups_from_matches(matches)
    for group_id, name in groups:
        await service.create_group(
            session,
            tournament,
            name=name,
            is_groups=True,
            challonge_id=group_id,
            challonge_slug=challonge_tournament.url,
        )
    await service.create_group(
        session,
        tournament,
        name="Playoffs",
        is_groups=False,
        challonge_slug=challonge_tournament.url,
    )

    return tournament


async def create_with_groups(
    session: AsyncSession,
    workspace_id: int,
    number: int,
    is_league: bool,
    start_date: date,
    end_date: date,
    challonge_slug: str,
    division_grid_version_id: int | None = None,
) -> models.Tournament:
    if await service.get_by_number(session, number, []) is not None:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="tournament_exists",
                    msg="Tournament with this number already exists",
                )
            ],
        )

    resolved_division_grid_version_id = division_grid_version_id
    if resolved_division_grid_version_id is None:
        resolved_division_grid_version_id = await get_workspace_division_grid_version_id(
            session, workspace_id
        )
    if resolved_division_grid_version_id is None:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="workspace_default_division_grid_missing",
                    msg="Workspace does not have a default division grid version",
                )
            ],
        )

    challonge_tournament = await challonge_service.fetch_tournament(challonge_slug)
    if challonge_tournament.grand_finals_modifier is None:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="invalid_tournament",
                    msg="Tournament does not have group stage",
                )
            ],
        )
    tournament = await service.create(
        session,
        workspace_id=workspace_id,
        number=number,
        is_league=is_league,
        name=challonge_tournament.name,
        description=challonge_tournament.description,
        challonge_id=challonge_tournament.id,
        challonge_slug=challonge_tournament.url,
        start_date=start_date,
        end_date=end_date,
        division_grid_version_id=resolved_division_grid_version_id,
    )
    tournament = await service.get(session, tournament.id, [])
    return await create_groups(session, tournament, challonge_tournament)


async def create(
    session: AsyncSession,
    number: int,
    is_league: bool,
    start_date: date,
    end_date: date,
    groups_challonge_slugs: list[str],
    playoffs_challonge_slug: str,
) -> models.Tournament:
    if await service.get_by_number_and_league(session, number, is_league, []) is not None:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="tournament_exists",
                    msg="Tournament with this number already exists",
                )
            ],
        )

    tournament = await service.create(
        session,
        workspace_id=1,
        number=number,
        name=f"Турнир Сабов Anakq #{number}",
        is_league=is_league,
        start_date=start_date,
        end_date=end_date,
    )

    for sym_index, slug in enumerate(groups_challonge_slugs, start=65):
        challonge_tournament = await challonge_service.fetch_tournament(slug)
        await service.create_group(
            session,
            tournament,
            name=chr(sym_index),
            is_groups=True,
            challonge_slug=challonge_tournament.url,
            challonge_id=challonge_tournament.id,
        )

    challonge_tournament = await challonge_service.fetch_tournament(playoffs_challonge_slug)
    await service.create_group(
        session,
        tournament,
        name="Playoffs",
        is_groups=False,
        challonge_slug=challonge_tournament.url,
        challonge_id=challonge_tournament.id,
    )
    return tournament
