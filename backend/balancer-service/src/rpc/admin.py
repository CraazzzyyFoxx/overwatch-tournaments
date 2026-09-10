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

from shared.services.balancer_realtime import BALANCER_TEAMS_CHANGED
from shared.services.realtime import Scope, emit, enqueue_invalidation_outbox
from src import models, schemas
from src.core import db
from src.core.auth import _get_balance_workspace_id, _get_tournament_workspace_id
from src.rpc import _common as c
from src.services.admin._mappers import serialize_balance, serialize_tournament_config
from src.services.admin.balancer import balancer_admin_service
from src.services.balancer.realtime import EXPORT_RESOURCES, emit_balancer_data

_SF = db.async_session_maker


def _config_to_read(
    cfg: models.WorkspaceBalancerConfig | None,
    workspace_id: int,
) -> schemas.WorkspaceBalancerConfigRead:
    if cfg is None:
        return schemas.WorkspaceBalancerConfigRead(
            id=0,
            workspace_id=workspace_id,
            rank_delta_threshold=None,
            rank_delta_hide_from_pool=False,
            updated_by=None,
        )
    payload = cfg.config_json or {}
    return schemas.WorkspaceBalancerConfigRead(
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
            cfg = await balancer_admin_service.get_tournament_config(session, tournament_id)
            return serialize_tournament_config(cfg) if cfg is not None else None

        return await c.envelope(logger, "admin.tournament_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.tournament_config_upsert")
    async def _tournament_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            body = schemas.BalancerTournamentConfigUpsert.model_validate(c.payload(data))
            cfg = await balancer_admin_service.upsert_tournament_config(
                session, tournament_id, ws_id, body.config_json, user
            )
            # The emit lives in the service: it owns the commit, and `emit`
            # only reaches the wire through the commit that carries the write.
            return serialize_tournament_config(cfg)

        return await c.envelope(logger, "admin.tournament_config_upsert", op, session_factory=_SF)

    # --- tournament summary (balancer tool context, D29) --------------------
    @broker.subscriber("rpc.balancer.admin.tournament_summary_get")
    async def _tournament_summary_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "read")
            # Tournament row, not config: id/name/status are non-nullable by
            # construction, and hidden tournaments stay visible (team.read gate).
            t = await balancer_admin_service.get_tournament_row(session, tournament_id)
            return {"id": t.id, "name": t.name, "status": t.status, "workspace_id": ws_id}

        return await c.envelope(logger, "admin.tournament_summary_get", op, session_factory=_SF)

    # --- saved balance ------------------------------------------------------
    @broker.subscriber("rpc.balancer.admin.balance_get")
    async def _balance_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "read")
            balance = await balancer_admin_service.get_balance(session, tournament_id)
            return serialize_balance(balance) if balance is not None else None

        return await c.envelope(logger, "admin.balance_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_save")
    async def _balance_save(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            body = schemas.BalanceSaveRequest.model_validate(c.payload(data))
            balance = await balancer_admin_service.save_balance(session, tournament_id, body, user)
            # Emitted inside `save_balance`, which owns the commit.
            return serialize_balance(balance, already_normalized=True)

        return await c.envelope(logger, "admin.balance_save", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_export")
    async def _balance_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            balance_id = c.require_id(data)
            ws_id = await _get_balance_workspace_id(session, balance_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            balance, removed_teams, imported_teams = await balancer_admin_service.export_balance(session, balance_id)
            await emit_balancer_data(session, balance.tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=user.id)
            # The balancer topic reaches only the admin tool. Materialization
            # rewrote tournament.team / player / standing, so the PUBLIC reads
            # are stale — named here, and mirrored to app-service (which caches
            # the same three) through the outbox.
            await emit(
                session,
                scope=Scope.tournament(balance.tournament_id),
                invalidates=EXPORT_RESOURCES,
            )
            await enqueue_invalidation_outbox(
                session, scope=Scope.tournament(balance.tournament_id), resources=EXPORT_RESOURCES
            )
            await session.commit()
            return schemas.BalanceExportResponse(
                success=True,
                removed_teams=removed_teams,
                imported_teams=imported_teams,
                balance_id=balance.id,
            )

        return await c.envelope(logger, "admin.balance_export", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_ranks_export")
    async def _balance_ranks_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            balance_id = c.require_id(data)
            ws_id = await _get_balance_workspace_id(session, balance_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            balance, updated = await balancer_admin_service.export_balance_ranks(session, balance_id)
            await emit_balancer_data(session, balance.tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=user.id)
            # Rank export rewrites tournament.player rows the public reads join.
            await emit(
                session,
                scope=Scope.tournament(balance.tournament_id),
                invalidates=EXPORT_RESOURCES,
            )
            await enqueue_invalidation_outbox(
                session, scope=Scope.tournament(balance.tournament_id), resources=EXPORT_RESOURCES
            )
            await session.commit()
            return schemas.RanksExportResponse(success=True, updated_players=updated)

        return await c.envelope(logger, "admin.balance_ranks_export", op, session_factory=_SF)

    # --- workspace balancer config -----------------------------------------
    @broker.subscriber("rpc.balancer.admin.workspace_config_get")
    async def _workspace_config_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            c.require_workspace_permission(data, user, workspace_id, "workspace", "read")
            cfg = await balancer_admin_service.get_workspace_balancer_config(session, workspace_id)
            return _config_to_read(cfg, workspace_id)

        return await c.envelope(logger, "admin.workspace_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.workspace_config_upsert")
    async def _workspace_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            c.require_workspace_permission(data, user, workspace_id, "workspace", "update")
            body = schemas.WorkspaceBalancerConfigUpsert.model_validate(c.payload(data))
            cfg = await balancer_admin_service.upsert_workspace_balancer_config(
                session,
                workspace_id=workspace_id,
                rank_delta_threshold=body.rank_delta_threshold,
                rank_delta_hide_from_pool=body.rank_delta_hide_from_pool,
                updated_by=user.id,
            )
            return _config_to_read(cfg, workspace_id)

        return await c.envelope(logger, "admin.workspace_config_upsert", op, session_factory=_SF)
