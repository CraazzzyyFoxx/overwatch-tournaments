"""Admin balancer endpoints over typed RPC.

Ports ``src/routes/admin/balancer.py`` (router-level ``require_admin_panel_access()``
+ per-endpoint workspace permission) to ``rpc.balancer.admin.*`` subscribers. Each
handler rehydrates the gateway identity, enforces the admin-panel gate and the
workspace RBAC, delegates to ``src/services/admin/balancer.py`` (which owns its
commit), then emits the same realtime data events as the HTTP routes.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.services.balancer_realtime import (
    BALANCER_BALANCE_SAVED,
    BALANCER_CONFIG_CHANGED,
    BALANCER_TEAMS_CHANGED,
)
from src import models
from src.core import db
from src.core.auth import _get_balance_workspace_id, _get_tournament_workspace_id
from src.rpc import _common as c
from src.schemas.admin import balancer as admin_schemas
from src.services.admin import balancer as admin_balancer
from src.services.admin._mappers import serialize_balance, serialize_tournament_config
from src.services.balancer.realtime import emit_balancer_data_event

_SF = db.async_session_maker


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


def register(broker: Any, logger: Any) -> None:
    # --- tournament balancer config ----------------------------------------
    @broker.subscriber("rpc.balancer.admin.tournament_config_get")
    async def _tournament_config_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "read")
            cfg = await admin_balancer.get_tournament_config(session, tournament_id)
            return serialize_tournament_config(cfg) if cfg is not None else None

        return await c.envelope(logger, "admin.tournament_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.tournament_config_upsert")
    async def _tournament_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            body = admin_schemas.BalancerTournamentConfigUpsert.model_validate(c.payload(data))
            cfg = await admin_balancer.upsert_tournament_config(session, tournament_id, body.config_json, user)
            await emit_balancer_data_event(
                tournament_id,
                BALANCER_CONFIG_CHANGED,
                workspace_id=cfg.workspace_id,
                actor_user_id=user.id,
            )
            return serialize_tournament_config(cfg)

        return await c.envelope(logger, "admin.tournament_config_upsert", op, session_factory=_SF)

    # --- saved balance ------------------------------------------------------
    @broker.subscriber("rpc.balancer.admin.balance_get")
    async def _balance_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "read")
            balance = await admin_balancer.get_balance(session, tournament_id)
            return serialize_balance(balance) if balance is not None else None

        return await c.envelope(logger, "admin.balance_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_save")
    async def _balance_save(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            body = admin_schemas.BalanceSaveRequest.model_validate(c.payload(data))
            balance = await admin_balancer.save_balance(session, tournament_id, body, user)
            await emit_balancer_data_event(tournament_id, BALANCER_BALANCE_SAVED, actor_user_id=user.id)
            return serialize_balance(balance)

        return await c.envelope(logger, "admin.balance_save", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_export")
    async def _balance_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            balance_id = c.require_id(data)
            ws_id = await _get_balance_workspace_id(session, balance_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            balance, removed_teams, imported_teams = await admin_balancer.export_balance(session, balance_id)
            await emit_balancer_data_event(balance.tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=user.id)
            return admin_schemas.BalanceExportResponse(
                success=True,
                removed_teams=removed_teams,
                imported_teams=imported_teams,
                balance_id=balance.id,
            )

        return await c.envelope(logger, "admin.balance_export", op, session_factory=_SF)

    # --- workspace balancer config -----------------------------------------
    @broker.subscriber("rpc.balancer.admin.workspace_config_get")
    async def _workspace_config_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            c.require_workspace_permission(data, user, workspace_id, "workspace", "read")
            cfg = await admin_balancer.get_workspace_balancer_config(session, workspace_id)
            return _config_to_read(cfg, workspace_id)

        return await c.envelope(logger, "admin.workspace_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.workspace_config_upsert")
    async def _workspace_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            c.require_workspace_permission(data, user, workspace_id, "workspace", "admin")
            body = admin_schemas.WorkspaceBalancerConfigUpsert.model_validate(c.payload(data))
            cfg = await admin_balancer.upsert_workspace_balancer_config(
                session,
                workspace_id=workspace_id,
                rank_delta_threshold=body.rank_delta_threshold,
                rank_delta_hide_from_pool=body.rank_delta_hide_from_pool,
                updated_by=user.id,
            )
            return _config_to_read(cfg, workspace_id)

        return await c.envelope(logger, "admin.workspace_config_upsert", op, session_factory=_SF)
