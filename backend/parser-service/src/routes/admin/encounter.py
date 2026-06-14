"""Admin routes for encounter CRUD operations"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db
from src.schemas.admin import encounter as admin_schemas
from src.services.admin import encounter as admin_service
from src.services.encounter import captain as captain_service
from src.services.encounter import flows as encounter_flows
from src.services.encounter import map_veto as map_veto_service

router = APIRouter(
    prefix="/encounters",
    tags=["admin", "encounters"],
)


@router.post("", response_model=schemas.EncounterRead)
async def create_encounter(
    data: admin_schemas.EncounterCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Create a new encounter (admin/organizer only)"""
    await auth.require_tournament_id_permission(
        session,
        user,
        tournament_id=data.tournament_id,
        resource="match",
        action="create",
    )
    encounter = await admin_service.create_encounter(session, data)
    return await encounter_flows.get_encounter(
        session,
        encounter.id,
        ["tournament", "stage", "stage_item", "home_team", "away_team"],
    )


@router.patch("/{encounter_id}", response_model=schemas.EncounterRead)
async def update_encounter(
    encounter_id: int,
    data: admin_schemas.EncounterUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_encounter_permission("match", "update")),
):
    """Update encounter fields (admin/organizer only)"""
    encounter = await admin_service.update_encounter(session, encounter_id, data)
    return await encounter_flows.get_encounter(
        session,
        encounter.id,
        ["tournament", "stage", "stage_item", "home_team", "away_team"],
    )


@router.delete("/{encounter_id}", status_code=204)
async def delete_encounter(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_encounter_permission("match", "delete")),
):
    """Delete encounter and all matches (admin/organizer only)"""
    await admin_service.delete_encounter(session, encounter_id)


@router.patch("/bulk")
async def bulk_update_encounters(
    data: admin_schemas.BulkEncounterUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    """Bulk-update encounters — mass-set status, scores, or reset.

    Critical for 40+ team tournaments: one transaction, one standings
    recalc per affected tournament (instead of N separate recalcs).
    """
    await auth.require_encounter_ids_permission(
        session,
        user,
        encounter_ids=data.encounter_ids,
        resource="match",
        action="update",
    )
    return await admin_service.bulk_update_encounters(session, data)


# ── Admin per-match (map) edits ──────────────────────────────────────────


@router.patch("/matches/{match_id}")
async def update_match(
    match_id: int,
    data: admin_schemas.MatchUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_match_permission("match", "update")),
):
    """Update a single match (map) within an encounter."""
    match = await admin_service.update_match(session, match_id, data)
    return {
        "id": match.id,
        "encounter_id": match.encounter_id,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "map_id": match.map_id,
        "code": match.code,
        "time": match.time,
        "log_name": match.log_name,
    }


# ── Admin result confirmation ────────────────────────────────────────────


@router.post("/{encounter_id}/confirm-result")
async def admin_confirm_result(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_encounter_permission("match", "update")),
):
    """Admin force-confirms a pending result without requiring the other captain."""
    encounter = await captain_service.admin_confirm_result(session, encounter_id)
    return {
        "id": encounter.id,
        "result_status": encounter.result_status,
        "status": encounter.status,
    }


# ── Admin map pool management ────────────────────────────────────────────


class AdminMapPoolAssign(BaseModel):
    map_ids: list[int]


@router.post("/{encounter_id}/map-pool")
async def admin_assign_map_pool(
    encounter_id: int,
    data: AdminMapPoolAssign,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_encounter_permission("match", "update")),
):
    """Admin directly assigns maps to an encounter (bypasses veto)."""
    entries = await map_veto_service.initialize_map_pool(
        session, encounter_id, data.map_ids,
    )
    return {"assigned": len(entries)}
