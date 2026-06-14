"""Public routes for captain result submission and map veto."""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.services.encounter import captain as captain_service
from src.services.encounter import map_veto as map_veto_service
from src.services.encounter.map_veto_ws import manager as map_veto_ws_manager

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
    closeness: int = Field(ge=1, le=5)


async def _resolve_websocket_viewer(
    websocket: WebSocket,
    session: AsyncSession,
    encounter: models.Encounter,
) -> tuple[models.AuthUser | None, str | None]:
    auth_user = await auth.get_websocket_user_optional(websocket, session)
    if auth_user is None:
        return None, None

    try:
        viewer_side = await captain_service.resolve_captain_side(session, auth_user, encounter)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return auth_user, None
        raise

    return auth_user, viewer_side


async def _broadcast_map_pool_state(encounter_id: int) -> None:
    sockets = list(map_veto_ws_manager.get_connections(encounter_id))
    if not sockets:
        return

    async with db.async_session_maker() as session:
        state_by_socket: dict[WebSocket, dict] = {}
        for socket in sockets:
            viewer_side = getattr(socket.state, "map_veto_viewer_side", None)
            state_by_socket[socket] = await map_veto_service.get_map_pool_state(
                session,
                encounter_id,
                viewer_side=viewer_side,
            )

    await map_veto_ws_manager.broadcast_state(encounter_id, state_by_socket)


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
        session, user, encounter_id, data.home_score, data.away_score,
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
        closeness_stars=data.closeness,
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
        session, user, encounter_id, data.reason,
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
        session, encounter_id, captain_side, data.map_id, data.action,
    )
    return {
        "id": entry.id,
        "map_id": entry.map_id,
        "status": entry.status,
        "picked_by": entry.picked_by,
    }


@router.websocket("/{encounter_id}/map-pool/ws")
async def map_pool_socket(
    websocket: WebSocket,
    encounter_id: int,
) -> None:
    await map_veto_ws_manager.connect(encounter_id, websocket)

    try:
        try:
            async with db.async_session_maker() as session:
                encounter = await captain_service._load_encounter(session, encounter_id)
                auth_user, viewer_side = await _resolve_websocket_viewer(websocket, session, encounter)
                websocket.state.map_veto_user_id = auth_user.id if auth_user is not None else None
                websocket.state.map_veto_viewer_side = viewer_side
                state = await map_veto_service.get_map_pool_state(
                    session,
                    encounter_id,
                    viewer_side=viewer_side,
                )
        except HTTPException as exc:
            await map_veto_ws_manager.send_error(
                websocket,
                code="map_pool_unavailable",
                message=str(exc.detail),
            )
            await websocket.close(code=1008)
            return

        await map_veto_ws_manager.send_state(websocket, state)

        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type")
            if message_type != "veto.action":
                await map_veto_ws_manager.send_error(
                    websocket,
                    code="unsupported_message",
                    message="Unsupported websocket message type",
                )
                continue

            if getattr(websocket.state, "map_veto_user_id", None) is None or getattr(
                websocket.state, "map_veto_viewer_side", None
            ) is None:
                await map_veto_ws_manager.send_error(
                    websocket,
                    code="forbidden",
                    message="Only captains can perform veto actions",
                )
                continue

            try:
                action = VetoAction.model_validate(payload)
            except ValidationError:
                await map_veto_ws_manager.send_error(
                    websocket,
                    code="invalid_payload",
                    message="Invalid veto action payload",
                )
                continue

            try:
                async with db.async_session_maker() as session:
                    await map_veto_service.perform_veto_action(
                        session,
                        encounter_id,
                        websocket.state.map_veto_viewer_side,
                        action.map_id,
                        action.action,
                    )
            except HTTPException as exc:
                await map_veto_ws_manager.send_error(
                    websocket,
                    code="veto_action_failed",
                    message=str(exc.detail),
                )

                async with db.async_session_maker() as session:
                    current_state = await map_veto_service.get_map_pool_state(
                        session,
                        encounter_id,
                        viewer_side=getattr(websocket.state, "map_veto_viewer_side", None),
                    )
                await map_veto_ws_manager.send_state(websocket, current_state)
                continue

            await _broadcast_map_pool_state(encounter_id)
    except WebSocketDisconnect:
        pass
    finally:
        map_veto_ws_manager.disconnect(encounter_id, websocket)
