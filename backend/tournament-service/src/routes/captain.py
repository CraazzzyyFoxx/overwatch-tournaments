"""Public routes for captain result submission and map veto."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.services.encounter import captain as captain_service
from src.services.encounter import map_veto as map_veto_service

router = APIRouter(
    prefix="/encounters",
    tags=["captain"],
)


# ── Schemas ──────────────────────────────────────────────────────────────


class ResultSubmission(BaseModel):
    home_score: int
    away_score: int


class DisputeRequest(BaseModel):
    reason: str | None = None


class VetoAction(BaseModel):
    map_id: int
    action: str  # "ban" or "pick"


class CaptainMatchReport(BaseModel):
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    closeness: int = Field(ge=1, le=10)


async def resolve_optional_viewer_side(
    session: AsyncSession,
    auth_user: models.AuthUser | None,
    encounter: models.Encounter,
) -> str | None:
    """Resolve a viewer's captain side for read-only annotation, or ``None``.

    Mirrors the old WebSocket viewer resolution: an authenticated captain gets
    their side ('home'/'away'); anonymous or non-captain viewers get ``None``
    (and see the pool serialized identically — ``viewer_side`` is presentation
    only). A 403 means "not a captain" and resolves to ``None``.
    """
    if auth_user is None:
        return None
    try:
        return await captain_service.resolve_captain_side(session, auth_user, encounter)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return None
        raise


# ── Captain identity check ───────────────────────────────────────────────


@router.get("/{encounter_id}/my-role")
async def get_my_role(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_user),
):
    """Return the captain side ('home'/'away') for the current user, or null."""
    encounter = await captain_service._load_encounter(session, encounter_id)
    try:
        side = await captain_service.resolve_captain_side(session, user, encounter)
    except HTTPException:
        side = None
    return {"side": side}


# ── Captain result submission ────────────────────────────────────────────


@router.post("/{encounter_id}/submit-result")
async def submit_result(
    encounter_id: int,
    data: ResultSubmission,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_user),
):
    """Captain submits match result. Other team's captain must confirm."""
    encounter = await captain_service.submit_result(
        session,
        user,
        encounter_id,
        data.home_score,
        data.away_score,
    )
    return {
        "id": encounter.id,
        "result_status": encounter.result_status,
        "home_score": encounter.home_score,
        "away_score": encounter.away_score,
    }


@router.post("/{encounter_id}/submit-match-report")
async def submit_match_report(
    encounter_id: int,
    data: CaptainMatchReport,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_user),
):
    """Captain submits the encounter result without creating per-map rows."""
    encounter = await captain_service.submit_match_report(
        session,
        user,
        encounter_id,
        home_score=data.home_score,
        away_score=data.away_score,
        closeness_score=data.closeness,
    )
    return {
        "id": encounter.id,
        "result_status": encounter.result_status,
        "home_score": encounter.home_score,
        "away_score": encounter.away_score,
        "closeness": encounter.closeness,
    }


@router.post("/{encounter_id}/confirm-result")
async def confirm_result(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_user),
):
    """Opposing captain confirms the submitted result."""
    encounter = await captain_service.confirm_result(session, user, encounter_id)
    return {
        "id": encounter.id,
        "result_status": encounter.result_status,
        "status": encounter.status,
    }


@router.post("/{encounter_id}/dispute-result")
async def dispute_result(
    encounter_id: int,
    data: DisputeRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_user),
):
    """Either captain disputes the submitted result. Admin resolves manually."""
    encounter = await captain_service.dispute_result(
        session,
        user,
        encounter_id,
        data.reason,
    )
    return {
        "id": encounter.id,
        "result_status": encounter.result_status,
    }


# ── Map veto ─────────────────────────────────────────────────────────────


@router.get("/{encounter_id}/map-pool")
async def get_map_pool(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
):
    """Get the current map pool state for an encounter."""
    pool = await map_veto_service.get_map_pool(session, encounter_id)
    return [map_veto_service.serialize_map_pool_entry(entry) for entry in pool]


@router.get("/{encounter_id}/map-pool/state")
async def get_map_pool_state(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser | None = Depends(auth.get_current_user_optional),
):
    """Get the full map-pool veto state for an encounter (optional auth).

    Replaces the previous map-pool WebSocket. The realtime hub now carries only a
    thin ``map_veto.updated`` signal on ``encounter:{id}:map-veto``; clients call
    this endpoint to (re)fetch the state. An authenticated captain sees their side
    annotated; everyone else gets the same pool with ``viewer_side=None``.
    """
    encounter = await captain_service._load_encounter(session, encounter_id)
    viewer_side = await resolve_optional_viewer_side(session, user, encounter)
    return await map_veto_service.get_map_pool_state(
        session,
        encounter_id,
        viewer_side=viewer_side,
    )


@router.post("/{encounter_id}/map-pool/veto")
async def perform_veto(
    encounter_id: int,
    data: VetoAction,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_user),
):
    """Captain performs a ban or pick action in the veto sequence."""
    encounter = await captain_service._load_encounter(session, encounter_id)
    captain_side = await captain_service.resolve_captain_side(session, user, encounter)

    entry = await map_veto_service.perform_veto_action(
        session,
        encounter_id,
        captain_side,
        data.map_id,
        data.action,
    )
    return {
        "id": entry.id,
        "map_id": entry.map_id,
        "status": entry.status,
        "picked_by": entry.picked_by,
    }
