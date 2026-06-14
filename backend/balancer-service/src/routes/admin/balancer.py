from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from shared.services.balancer_realtime import (
    BALANCER_BALANCE_SAVED,
    BALANCER_CONFIG_CHANGED,
    BALANCER_TEAMS_CHANGED,
)

from src import models
from src.core import auth, db
from src.schemas.admin import balancer as admin_schemas
from src.schemas.team import BalancerTeam, InternalBalancerTeamsPayload
from src.services import team as team_service
from src.services.admin import balancer as admin_balancer
from src.services.admin._mappers import (
    serialize_balance as _serialize_balance,
    serialize_tournament_config as _serialize_tournament_config,
)
from src.services.balancer.realtime import emit_balancer_data_event

router = APIRouter(
    prefix="/balancer",
    tags=["balancer"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)


@router.get(
    "/tournaments/{tournament_id}/config",
    response_model=admin_schemas.BalancerTournamentConfigRead | None,
)
async def get_tournament_config(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    tournament_config = await admin_balancer.get_tournament_config(session, tournament_id)
    if tournament_config is None:
        return None
    return _serialize_tournament_config(tournament_config)


@router.put(
    "/tournaments/{tournament_id}/config",
    response_model=admin_schemas.BalancerTournamentConfigRead,
)
async def upsert_tournament_config(
    tournament_id: int,
    data: admin_schemas.BalancerTournamentConfigUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    tournament_config = await admin_balancer.upsert_tournament_config(
        session, tournament_id, data.config_json, user
    )
    await emit_balancer_data_event(
        tournament_id,
        BALANCER_CONFIG_CHANGED,
        workspace_id=tournament_config.workspace_id,
        actor_user_id=user.id,
    )
    return _serialize_tournament_config(tournament_config)


@router.get("/tournaments/{tournament_id}/balance", response_model=admin_schemas.BalanceRead | None)
async def get_balance(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    balance = await admin_balancer.get_balance(session, tournament_id)
    if balance is None:
        return None
    return _serialize_balance(balance)


@router.put("/tournaments/{tournament_id}/balance", response_model=admin_schemas.BalanceRead)
async def save_balance(
    tournament_id: int,
    data: admin_schemas.BalanceSaveRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    balance = await admin_balancer.save_balance(session, tournament_id, data, user)
    await emit_balancer_data_event(
        tournament_id,
        BALANCER_BALANCE_SAVED,
        actor_user_id=user.id,
    )
    return _serialize_balance(balance)


@router.post("/balances/{balance_id}/export", response_model=admin_schemas.BalanceExportResponse)
async def export_balance(
    balance_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_balance_permission("team", "import")),
):
    balance, removed_teams, imported_teams = await admin_balancer.export_balance(session, balance_id)
    await emit_balancer_data_event(
        balance.tournament_id,
        BALANCER_TEAMS_CHANGED,
        actor_user_id=user.id,
    )
    return admin_schemas.BalanceExportResponse(
        success=True,
        removed_teams=removed_teams,
        imported_teams=imported_teams,
        balance_id=balance.id,
    )


def _config_to_read(
    cfg: models.WorkspaceBalancerConfig | None,
    workspace_id: int,
) -> admin_schemas.WorkspaceBalancerConfigRead:
    if cfg is None:
        return admin_schemas.WorkspaceBalancerConfigRead(
            id=0,
            workspace_id=workspace_id,
            rank_delta_threshold=None,
            rank_delta_hide_from_pool=False,
            updated_by=None,
        )
    payload = cfg.config_json or {}
    return admin_schemas.WorkspaceBalancerConfigRead(
        id=cfg.id,
        workspace_id=cfg.workspace_id,
        rank_delta_threshold=payload.get("rank_delta_threshold"),
        rank_delta_hide_from_pool=bool(payload.get("rank_delta_hide_from_pool", False)),
        updated_by=cfg.updated_by,
    )


@router.get(
    "/workspaces/{workspace_id}/config",
    response_model=admin_schemas.WorkspaceBalancerConfigRead,
)
async def get_workspace_balancer_config(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("workspace", "read")),
):
    cfg = await admin_balancer.get_workspace_balancer_config(session, workspace_id)
    return _config_to_read(cfg, workspace_id)


@router.put(
    "/workspaces/{workspace_id}/config",
    response_model=admin_schemas.WorkspaceBalancerConfigRead,
)
async def upsert_workspace_balancer_config(
    workspace_id: int,
    data: admin_schemas.WorkspaceBalancerConfigUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("workspace", "admin")),
):
    cfg = await admin_balancer.upsert_workspace_balancer_config(
        session,
        workspace_id=workspace_id,
        rank_delta_threshold=data.rank_delta_threshold,
        rank_delta_hide_from_pool=data.rank_delta_hide_from_pool,
        updated_by=user.id,
    )
    return _config_to_read(cfg, workspace_id)


@router.post("/tournaments/{tournament_id}/teams/import")
async def import_teams_from_json(
    tournament_id: int,
    data: UploadFile = File(...),
    payload_format: Literal["auto", "atravkovs", "internal"] = Form(default="auto"),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    payload = json.loads((await data.read()).decode("utf-8"))

    use_atravkovs = payload_format == "atravkovs" or (
        payload_format == "auto"
        and isinstance(payload, dict)
        and isinstance(payload.get("data"), dict)
        and "teams" in payload["data"]
    )

    if use_atravkovs:
        teams = [BalancerTeam.model_validate(team) for team in payload["data"]["teams"]]
    else:
        internal_payload = InternalBalancerTeamsPayload.model_validate(payload)
        teams = [team.to_balancer_team() for team in internal_payload.teams]

    await team_service.bulk_create_from_balancer(session, tournament_id, teams)
    await emit_balancer_data_event(
        tournament_id,
        BALANCER_TEAMS_CHANGED,
        actor_user_id=user.id,
    )
    return {"imported_teams": len(teams)}
