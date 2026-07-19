import asyncio
import typing
from datetime import date

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.services.challonge_refs import (
    ChallongeRef,
    resolve_stage_challonge,
    resolve_tournament_challonge,
)
from shared.services.division_grid_access import get_workspace_division_grid_version_id
from src import models, schemas
from src.core import errors
from src.services.challonge import service as challonge_service

from . import service


def _apply_stage_challonge(
    stage_read: schemas.StageRead,
    stage_id: int,
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None,
) -> schemas.StageRead:
    """Override the KEPT ``challonge_id``/``challonge_slug`` fields with values
    DERIVED from ``challonge_source`` (never the legacy ``stage`` columns)."""
    challonge_id, challonge_slug = (
        stage_challonge_refs.get(stage_id, (None, None)) if stage_challonge_refs is not None else (None, None)
    )
    return stage_read.model_copy(update={"challonge_id": challonge_id, "challonge_slug": challonge_slug})


async def to_pydantic(
    session: AsyncSession,
    tournament: models.Tournament,
    entities: list[str],
    *,
    challonge_ref: ChallongeRef | None = None,
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None,
) -> schemas.TournamentRead:
    """Serialize a tournament.

    ``challonge_ref``/``stage_challonge_refs`` carry the KEPT ``challonge_id``/
    ``challonge_slug`` response fields DERIVED from ``challonge_source`` (see
    ``shared.services.challonge_refs``) so the serializer never reads the
    deprecated ``tournament``/``stage`` columns. When omitted the fields
    serialize as ``None`` (callers that need them resolve/pass them).
    """
    stages: list[schemas.StageRead] = []
    if "stages" in entities:
        stages = [
            _apply_stage_challonge(
                schemas.StageRead.model_validate(stage, from_attributes=True),
                stage.id,
                stage_challonge_refs,
            )
            for stage in sorted(tournament.stages, key=lambda item: item.order)
        ]
    tournament_challonge_id, tournament_challonge_slug = challonge_ref if challonge_ref is not None else (None, None)
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
        challonge_id=tournament_challonge_id,
        challonge_slug=tournament_challonge_slug,
        auto_transitions_enabled=tournament.auto_transitions_enabled,
        allow_late_registration=tournament.allow_late_registration,
        phase_schedule=[
            schemas.TournamentPhaseScheduleRead.model_validate(entry, from_attributes=True)
            for entry in tournament.phase_schedule
        ],
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
    session: AsyncSession,
    group: models.TournamentGroup,
    entities: list[str],
) -> schemas.TournamentGroupRead:
    """Serialize a tournament group.

    ``group.challonge_id``/``challonge_slug`` is a KEPT column (dbarch04b does NOT
    drop it — it holds Challonge's per-group match-routing id, which has no
    ``challonge_source`` equivalent). Read it directly; do NOT derive it from
    ``challonge_source`` (the shared bracket is a stage/tournament-scoped source, so
    a group-scoped lookup would wrongly return NULL for historical tournaments).
    """
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
    # Batched Challonge-ref derivation (no N+1): one query for the tournament and
    # one for its loaded stages when requested, from challonge_source.
    challonge_ref = (await resolve_tournament_challonge(session, [tournament.id])).get(tournament.id)
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None
    if "stages" in entities:
        stage_challonge_refs = await resolve_stage_challonge(session, [stage.id for stage in tournament.stages])
    return await to_pydantic(
        session,
        tournament,
        entities,
        challonge_ref=challonge_ref,
        stage_challonge_refs=stage_challonge_refs,
    )


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
    # Release the DB connection before the Challonge round-trip: under
    # pgBouncer/NullPool an open transaction pins a backend slot for the whole
    # network wait. expire_on_commit=False keeps ``tournament`` usable.
    await session.commit()
    matches = await challonge_service.fetch_matches(challonge_tournament.id)
    for match in matches:
        logger.info(match)
    groups = get_groups_from_matches(matches)

    specs = [
        service.GroupSpec(
            name=name,
            is_groups=True,
            challonge_id=group_id,
            challonge_slug=challonge_tournament.url,
        )
        for group_id, name in groups
    ]
    specs.append(
        service.GroupSpec(
            name="Playoffs",
            is_groups=False,
            challonge_slug=challonge_tournament.url,
        )
    )
    await service.create_groups(session, tournament, specs)

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
        resolved_division_grid_version_id = await get_workspace_division_grid_version_id(session, workspace_id)
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

    # Commit before the Challonge round-trip so no transaction (opened by the
    # reads above) stays pinned to a pgBouncer slot during the network wait.
    await session.commit()
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
        start_date=start_date,
        end_date=end_date,
        division_grid_version_id=resolved_division_grid_version_id,
    )
    # Link the tournament to Challonge through the normalized challonge_source
    # (source_type='tournament') instead of the deprecated tournament.challonge_id/
    # slug columns. discover_sources reads this row on import/export.
    session.add(
        models.ChallongeSource(
            tournament_id=tournament.id,
            challonge_tournament_id=challonge_tournament.id,
            slug=challonge_tournament.url,
            source_type="tournament",
        )
    )
    await session.commit()
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

    # Commit before the Challonge round-trips (the existence check above opened
    # a transaction), then fetch every group/playoff bracket concurrently
    # instead of one serial HTTP call per slug under an open session.
    await session.commit()

    semaphore = asyncio.Semaphore(4)

    async def _fetch_tournament(slug: str) -> schemas.ChallongeTournament:
        async with semaphore:
            return await challonge_service.fetch_tournament(slug)

    fetched = await asyncio.gather(
        *(_fetch_tournament(slug) for slug in [*groups_challonge_slugs, playoffs_challonge_slug])
    )
    group_tournaments, playoffs_tournament = fetched[:-1], fetched[-1]

    tournament = await service.create(
        session,
        workspace_id=1,
        number=number,
        name=f"Турнир Сабов Anakq #{number}",
        is_league=is_league,
        start_date=start_date,
        end_date=end_date,
    )

    specs = [
        service.GroupSpec(
            name=chr(sym_index),
            is_groups=True,
            challonge_slug=challonge_tournament.url,
            challonge_id=challonge_tournament.id,
        )
        for sym_index, challonge_tournament in enumerate(group_tournaments, start=65)
    ]
    specs.append(
        service.GroupSpec(
            name="Playoffs",
            is_groups=False,
            challonge_slug=playoffs_tournament.url,
            challonge_id=playoffs_tournament.id,
        )
    )
    await service.create_groups(session, tournament, specs)
    return tournament
