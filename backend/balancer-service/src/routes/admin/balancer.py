from __future__ import annotations

import json
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.composition import build_admin_balancer_use_cases
from src.core import auth, db
from src.presentation.http.admin_balancer_serializers import (
    serialize_application as _serialize_application,
)
from src.presentation.http.admin_balancer_serializers import (
    serialize_balance as _serialize_balance,
)
from src.presentation.http.admin_balancer_serializers import (
    serialize_feed as _serialize_feed,
)
from src.presentation.http.admin_balancer_serializers import (
    serialize_player as _serialize_player,
)
from src.presentation.http.admin_balancer_serializers import (
    serialize_tournament_config as _serialize_tournament_config,
)
from src.schemas.admin import balancer as admin_schemas
from src.schemas.team import BalancerTeam, InternalBalancerTeamsPayload
from src.services.admin.balancer import (
    fetch_latest_ow_ranks_by_user_ids,
    normalize_ow_ranks_to_grid,
)
from src.services.admin.balancer_registration import get_tournament_grid

router = APIRouter(
    prefix="/balancer",
    tags=["balancer"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)
use_cases = build_admin_balancer_use_cases()


@router.get(
    "/tournaments/{tournament_id}/sheet",
    response_model=admin_schemas.BalancerGoogleSheetFeedRead | None,
)
async def get_tournament_sheet(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    feed = await use_cases.get_tournament_sheet.execute(session=session, tournament_id=tournament_id)
    if feed is None:
        return None
    return _serialize_feed(feed)


@router.put(
    "/tournaments/{tournament_id}/sheet",
    response_model=admin_schemas.BalancerGoogleSheetFeedRead,
)
async def upsert_tournament_sheet(
    tournament_id: int,
    data: admin_schemas.BalancerGoogleSheetFeedUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    feed = await use_cases.upsert_tournament_sheet.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
    )
    return _serialize_feed(feed)


@router.post(
    "/tournaments/{tournament_id}/sheet/sync",
    response_model=admin_schemas.BalancerGoogleSheetFeedSyncResponse,
)
async def sync_tournament_sheet(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    feed, created, updated, withdrawn, total = await use_cases.sync_tournament_sheet.execute(
        session=session,
        tournament_id=tournament_id,
    )
    return admin_schemas.BalancerGoogleSheetFeedSyncResponse(
        created=created,
        updated=updated,
        withdrawn=withdrawn,
        total=total,
        feed=_serialize_feed(feed),
    )


@router.post(
    "/tournaments/{tournament_id}/sheet/suggest-mapping",
    response_model=admin_schemas.BalancerGoogleSheetMappingSuggestResponse,
)
async def suggest_sheet_mapping(
    tournament_id: int,
    data: admin_schemas.BalancerGoogleSheetMappingSuggestRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    _, headers, mapping = await use_cases.suggest_tournament_sheet_mapping.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
    )
    return admin_schemas.BalancerGoogleSheetMappingSuggestResponse(
        headers=headers,
        mapping_config_json=mapping,
    )


@router.post(
    "/tournaments/{tournament_id}/sheet/preview",
    response_model=admin_schemas.BalancerGoogleSheetMappingPreviewResponse,
)
async def preview_sheet_mapping(
    tournament_id: int,
    data: admin_schemas.BalancerGoogleSheetMappingPreviewRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    preview = await use_cases.preview_tournament_sheet_mapping.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
    )
    return admin_schemas.BalancerGoogleSheetMappingPreviewResponse(**preview)


@router.get("/tournaments/{tournament_id}/applications", response_model=list[admin_schemas.BalancerApplicationRead])
async def list_applications(
    tournament_id: int,
    include_inactive: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    applications = await use_cases.list_applications.execute(
        session=session,
        tournament_id=tournament_id,
        include_inactive=include_inactive,
    )
    return [_serialize_application(application) for application in applications]


@router.post("/tournaments/{tournament_id}/players", response_model=list[admin_schemas.BalancerPlayerRead])
async def create_players_from_applications(
    tournament_id: int,
    data: admin_schemas.BalancerPlayerCreateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "create")),
):
    players = await use_cases.create_players_from_applications.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
    )
    return [_serialize_player(player) for player in players]


@router.get("/tournaments/{tournament_id}/players", response_model=list[admin_schemas.BalancerPlayerRead])
async def list_players(
    tournament_id: int,
    in_pool_only: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "read")),
):
    players = await use_cases.list_players.execute(
        session=session,
        tournament_id=tournament_id,
        in_pool_only=in_pool_only,
    )
    user_ids = [p.user_id for p in players if p.user_id is not None]
    grid = await get_tournament_grid(session, tournament_id)
    ow_ranks = await fetch_latest_ow_ranks_by_user_ids(session, user_ids)
    ow_ranks = normalize_ow_ranks_to_grid(ow_ranks, grid)
    return [_serialize_player(p, ow_ranks.get(p.user_id)) for p in players]


@router.get("/users/{user_id}/players", response_model=list[admin_schemas.BalancerPlayerHistoryRead])
async def get_user_balancer_history(
    user_id: int,
    workspace_id: int | None = None,
    session: AsyncSession = Depends(db.get_async_session),
):
    """Return all BalancerPlayer records for a user, optionally scoped to a workspace.

    Results are sorted by tournament.number DESC (newest first) so the caller can
    take the latest entry per role without additional sorting.
    """
    query = (
        sa.select(models.BalancerPlayer, models.Tournament.number.label("tournament_number"))
        .join(models.Tournament, models.Tournament.id == models.BalancerPlayer.tournament_id)
        .where(models.BalancerPlayer.user_id == user_id)
        .options(selectinload(models.BalancerPlayer.role_entries))
        .order_by(models.Tournament.number.desc().nullslast(), models.BalancerPlayer.tournament_id.desc())
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)

    rows = (await session.execute(query)).all()

    history: list[admin_schemas.BalancerPlayerHistoryRead] = []
    for player, tournament_number in rows:
        base = _serialize_player(player)
        history.append(
            admin_schemas.BalancerPlayerHistoryRead(
                **base.model_dump(),
                tournament_number=tournament_number,
            )
        )
    return history


@router.patch("/players/{player_id}", response_model=admin_schemas.BalancerPlayerRead)
async def update_player(
    player_id: int,
    data: admin_schemas.BalancerPlayerUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_player_permission("player", "update")),
):
    player = await use_cases.update_player.execute(
        session=session,
        player_id=player_id,
        payload=data,
    )
    return _serialize_player(player)


@router.delete("/players/{player_id}", status_code=204)
async def delete_player(
    player_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_player_permission("player", "delete")),
):
    await use_cases.delete_player.execute(session=session, player_id=player_id)


@router.post(
    "/tournaments/{tournament_id}/players/import/preview",
    response_model=admin_schemas.BalancerPlayerImportPreviewResponse,
)
async def preview_player_import(
    tournament_id: int,
    data: UploadFile = File(...),
    match_application_roles: bool = Form(default=False),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "update")),
):
    payload = json.loads((await data.read()).decode("utf-8"))
    return await use_cases.preview_player_import.execute(
        session=session,
        tournament_id=tournament_id,
        payload=payload,
        match_application_roles=match_application_roles,
    )


@router.post(
    "/tournaments/{tournament_id}/players/import",
    response_model=admin_schemas.BalancerPlayerImportResult,
)
async def import_players(
    tournament_id: int,
    data: UploadFile = File(...),
    duplicate_strategy: admin_schemas.DuplicateStrategy = Form(...),
    match_application_roles: bool = Form(default=False),
    resolutions_json: str | None = Form(default=None),
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "update")),
):
    payload = json.loads((await data.read()).decode("utf-8"))
    resolutions = json.loads(resolutions_json) if resolutions_json else None
    return await use_cases.import_players.execute(
        session=session,
        tournament_id=tournament_id,
        payload=payload,
        duplicate_strategy=duplicate_strategy,
        resolutions=resolutions,
        match_application_roles=match_application_roles,
    )


@router.get("/tournaments/{tournament_id}/players/export", response_model=admin_schemas.BalancerPlayerExportResponse)
async def export_players(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "read")),
):
    payload = await use_cases.export_players.execute(session=session, tournament_id=tournament_id)
    return admin_schemas.BalancerPlayerExportResponse(**payload)


@router.post(
    "/tournaments/{tournament_id}/applications/export-users",
    response_model=admin_schemas.ApplicationUserExportResponse,
)
async def export_applications_to_users(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "import")),
):
    return await use_cases.export_applications_to_users.execute(
        session=session,
        tournament_id=tournament_id,
    )


@router.post(
    "/tournaments/{tournament_id}/players/application-roles",
    response_model=admin_schemas.BalancerPlayerRoleSyncResponse,
)
async def sync_player_roles_from_applications(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "update")),
):
    return await use_cases.sync_player_roles_from_applications.execute(
        session=session,
        tournament_id=tournament_id,
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
