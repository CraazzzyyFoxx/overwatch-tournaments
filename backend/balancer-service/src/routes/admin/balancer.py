from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.composition import build_admin_balancer_use_cases
from src.core import auth, db
from src.presentation.http.admin_balancer_serializers import (
    serialize_balance as _serialize_balance,
)
from src.presentation.http.admin_balancer_serializers import (
    serialize_tournament_config as _serialize_tournament_config,
)
from src.schemas.admin import balancer as admin_schemas
from src.schemas.team import BalancerTeam, InternalBalancerTeamsPayload

router = APIRouter(
    prefix="/balancer",
    tags=["balancer"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)
use_cases = build_admin_balancer_use_cases()


@router.get(
    "/tournaments/{tournament_id}/config",
    response_model=admin_schemas.BalancerTournamentConfigRead | None,
)
async def get_tournament_config(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    tournament_config = await use_cases.get_tournament_config.execute(
        session=session,
        tournament_id=tournament_id,
    )
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
    tournament_config = await use_cases.upsert_tournament_config.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
        user=user,
    )
    return _serialize_tournament_config(tournament_config)


@router.get("/tournaments/{tournament_id}/balance", response_model=admin_schemas.BalanceRead | None)
async def get_balance(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    balance = await use_cases.get_saved_balance.execute(session=session, tournament_id=tournament_id)
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
    balance = await use_cases.save_balance.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
        user=user,
    )
    return _serialize_balance(balance)


@router.post("/balances/{balance_id}/export", response_model=admin_schemas.BalanceExportResponse)
async def export_balance(
    balance_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_balance_permission("team", "import")),
):
    balance, removed_teams, imported_teams = await use_cases.export_balance.execute(
        session=session,
        balance_id=balance_id,
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
    cfg = await use_cases.get_workspace_balancer_config.execute(
        session=session, workspace_id=workspace_id
    )
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
    cfg = await use_cases.upsert_workspace_balancer_config.execute(
        session=session,
        workspace_id=workspace_id,
        payload=data,
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

    await use_cases.import_teams_from_json.execute(
        session=session,
        tournament_id=tournament_id,
        teams=teams,
    )
    return {"imported_teams": len(teams)}
