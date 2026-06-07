"""Admin service layer for tournament CRUD operations"""

from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import HTTPException, status
from shared.core import tournament_state
from shared.core.enums import StageType, TournamentStatus
from shared.services import division_grid_cache
from shared.services.division_grid_access import get_workspace_division_grid_version_id
from shared.services.tournament_computation import request_bracket_job
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.schemas.admin import tournament as admin_schemas
from src.services.admin import stage as stage_service
from src.services.challonge import service as challonge_service

GROUP_STAGE_TYPES = {StageType.ROUND_ROBIN, StageType.SWISS}


def _normalize_challonge_slug(value: str) -> str:
    slug = value.strip()
    if not slug:
        return ""

    if "://" not in slug and "." not in slug:
        return slug.strip("/")

    candidate = slug if "://" in slug else f"https://{slug}"
    parsed = urlparse(candidate)
    if "challonge.com" in parsed.netloc:
        path = parsed.path.strip("/")
        if path:
            return path.split("/")[-1]

    return slug.strip("/").split("/")[-1]


async def _resolve_division_grid_version_id(
    session: AsyncSession,
    *,
    workspace_id: int,
    division_grid_version_id: int | None,
) -> int:
    resolved_version_id = division_grid_version_id
    if resolved_version_id is None:
        resolved_version_id = await get_workspace_division_grid_version_id(session, workspace_id)

    if resolved_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace does not have a default division grid version",
        )

    version_workspace = await session.scalar(
        select(models.DivisionGrid.workspace_id)
        .join(models.DivisionGridVersion, models.DivisionGridVersion.grid_id == models.DivisionGrid.id)
        .where(models.DivisionGridVersion.id == resolved_version_id)
    )
    if version_workspace not in {None, workspace_id}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Division grid version does not belong to this workspace",
        )

    return int(resolved_version_id)


async def get_tournament(session: AsyncSession, tournament_id: int) -> models.Tournament:
    """Get one tournament with stages loaded for admin workspaces."""
    result = await session.execute(
        select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
    )
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    return tournament


async def create_tournament(session: AsyncSession, data: admin_schemas.TournamentCreate) -> models.Tournament:
    """Create a new tournament"""
    if data.number is not None:
        result = await session.execute(
            select(models.Tournament).where(
                models.Tournament.workspace_id == data.workspace_id,
                models.Tournament.number == data.number,
                models.Tournament.is_league == data.is_league,
            )
        )
        existing_tournament = result.scalar_one_or_none()

        if existing_tournament:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tournament with this number already exists in this workspace",
            )

    payload = data.model_dump()
    payload["division_grid_version_id"] = await _resolve_division_grid_version_id(
        session,
        workspace_id=data.workspace_id,
        division_grid_version_id=data.division_grid_version_id,
    )

    tournament = models.Tournament(**payload)

    session.add(tournament)
    await session.commit()
    await division_grid_cache.invalidate_tournament(tournament.id)
    await division_grid_cache.invalidate_workspace(tournament.workspace_id)
    return await get_tournament(session, tournament.id)


async def update_tournament(
    session: AsyncSession, tournament_id: int, data: admin_schemas.TournamentUpdate
) -> models.Tournament:
    """Update tournament fields"""
    # Fetch tournament
    result = await session.execute(
        select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
    )
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    if "challonge_slug" in update_data:
        raw_slug = update_data.pop("challonge_slug")
        if raw_slug:
            challonge_slug = _normalize_challonge_slug(raw_slug)
            challonge_tournament = await challonge_service.fetch_tournament(challonge_slug)
            tournament.challonge_slug = challonge_tournament.url
            tournament.challonge_id = challonge_tournament.id
        else:
            tournament.challonge_slug = None
            tournament.challonge_id = None

    if "division_grid_version_id" in update_data:
        update_data["division_grid_version_id"] = await _resolve_division_grid_version_id(
            session,
            workspace_id=tournament.workspace_id,
            division_grid_version_id=update_data["division_grid_version_id"],
        )

    should_invalidate_grid = "division_grid_version_id" in update_data and (
        update_data["division_grid_version_id"] != tournament.division_grid_version_id
    )

    for field, value in update_data.items():
        setattr(tournament, field, value)

    await session.commit()
    if should_invalidate_grid:
        await division_grid_cache.invalidate_tournament(tournament_id)
        await division_grid_cache.invalidate_workspace(tournament.workspace_id)
    return await get_tournament(session, tournament_id)


async def delete_tournament(session: AsyncSession, tournament_id: int) -> None:
    """Delete tournament (cascade deletes groups, teams, etc.)"""
    result = await session.execute(select(models.Tournament).where(models.Tournament.id == tournament_id))
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    workspace_id = tournament.workspace_id
    await session.execute(delete(models.Standing).where(models.Standing.tournament_id == tournament_id))
    await session.delete(tournament)
    await session.commit()
    await division_grid_cache.invalidate_tournament(tournament_id)
    await division_grid_cache.invalidate_workspace(workspace_id)


def _stage_has_ready_inputs(stage: models.Stage) -> bool:
    stage_items = list(getattr(stage, "items", []) or [])
    if not stage_items:
        return False

    for item in stage_items:
        team_count = sum(
            1 for stage_input in getattr(item, "inputs", []) if stage_input.team_id is not None
        )
        if team_count < 2:
            return False
    return True


async def _stage_has_encounters(session: AsyncSession, stage_id: int) -> bool:
    count = await session.scalar(
        sa.select(sa.func.count(models.Encounter.id)).where(models.Encounter.stage_id == stage_id)
    )
    return bool(count)


async def _maybe_auto_start_group_stage(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    target_status: TournamentStatus,
) -> None:
    if target_status != TournamentStatus.LIVE:
        return

    stages = sorted(getattr(tournament, "stages", []) or [], key=lambda stage: stage.order)
    group_stages = [
        stage
        for stage in stages
        if stage.stage_type in GROUP_STAGE_TYPES and not getattr(stage, "is_completed", False)
    ]
    if not group_stages:
        return

    active_stage = next((stage for stage in group_stages if getattr(stage, "is_active", False)), None)
    target_stage = active_stage or group_stages[0]
    has_encounters = await _stage_has_encounters(session, target_stage.id)

    if not active_stage:
        if not has_encounters and not _stage_has_ready_inputs(target_stage):
            return
        if has_encounters:
            await stage_service.activate_stage(session, target_stage.id)
        else:
            await request_bracket_job(
                session,
                tournament_id=tournament.id,
                stage_id=target_stage.id,
                operation="activate_and_generate",
            )
            return

    if not has_encounters and _stage_has_ready_inputs(target_stage):
        await request_bracket_job(
            session,
            tournament_id=tournament.id,
            stage_id=target_stage.id,
            operation="generate_stage",
        )


async def toggle_finished(session: AsyncSession, tournament_id: int) -> models.Tournament:
    """Toggle tournament is_finished flag (legacy — prefer transition_status)"""
    result = await session.execute(
        select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
    )
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    tournament.is_finished = not tournament.is_finished
    tournament.status = (
        TournamentStatus.COMPLETED if tournament.is_finished else TournamentStatus.LIVE
    )

    await session.commit()
    return await get_tournament(session, tournament_id)


async def transition_status(
    session: AsyncSession,
    tournament_id: int,
    target_status: TournamentStatus,
    *,
    force: bool = False,
) -> models.Tournament:
    """Transition tournament to a new status with state machine validation."""
    result = await session.execute(
        select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs)
        )
    )
    tournament = result.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    if not force:
        tournament_state.validate_transition(tournament.status, target_status)

    tournament.status = target_status
    tournament.is_finished = tournament_state.is_finished_for_status(target_status)

    await session.commit()
    await _maybe_auto_start_group_stage(
        session,
        tournament,
        target_status=target_status,
    )
    return await get_tournament(session, tournament_id)


# ─── Tournament Group Management ─────────────────────────────────────────────
