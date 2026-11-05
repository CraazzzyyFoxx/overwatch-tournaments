"""Admin balancer endpoints over typed RPC (``rpc.balancer.admin.*``).

Each handler rehydrates the gateway identity, enforces the admin-panel gate and
the workspace RBAC, then delegates to ``src/services/admin/balancer.py``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from faststream.rabbit import RabbitMessage

from shared import models, quota
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import WorkspaceRepository
from shared.rpc.identity import ensure_workspace_permission
from shared.services.discord_client import DiscordClient
from src import schemas
from src.core import db
from src.core.auth import _get_balance_workspace_id, _get_tournament_workspace_id
from src.rpc import _common as c
from src.services.admin._mappers import serialize_balance, serialize_tournament_config
from src.services.admin.balancer import balancer_admin_service
from src.services.formation_node import require_formation_node
from src.services.mix_ranker import mix_ranker_service, settings_from_json

_SF = db.async_session_maker


async def _ensure_workspace_exists(session: Any, workspace_id: int) -> None:
    """404 before a workspace config write, which would otherwise surface a missing workspace as an FK 500."""
    if not await WorkspaceRepository().exists(session, id=workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")


def _stored_mix_channel(cfg: models.WorkspaceBalancerConfig | None) -> str | None:
    """The saved mix channel the way the wire spells it: digits as a string, or ``None``."""
    channel = (cfg.config_json or {}).get("mix_discord_channel_id") if cfg is not None else None
    return str(channel) if channel else None


def _stored_voice(cfg: models.WorkspaceBalancerConfig | None) -> tuple[str | None, list[str]]:
    """The saved voice category and general voices, the way the wire spells them."""
    payload = (cfg.config_json or {}) if cfg is not None else {}
    category = payload.get("mix_voice_category_id")
    return (str(category) if category else None), [str(v) for v in payload.get("mix_general_voice_channel_ids") or []]


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
            mix_discord_channel_id=None,
            mix_voice_category_id=None,
            mix_general_voice_channel_ids=[],
            updated_by=None,
        )
    category, generals = _stored_voice(cfg)
    payload = cfg.config_json or {}
    channel = _stored_mix_channel(cfg)
    return schemas.WorkspaceBalancerConfigRead(
        id=cfg.id,
        workspace_id=cfg.workspace_id,
        rank_delta_threshold=payload.get("rank_delta_threshold"),
        rank_delta_hide_from_pool=bool(payload.get("rank_delta_hide_from_pool", False)),
        mix_discord_channel_id=channel,
        mix_voice_category_id=category,
        mix_general_voice_channel_ids=generals,
        updated_by=cfg.updated_by,
    )


async def _ranker_read(session: Any, workspace_id: int) -> schemas.WorkspaceRankerRead:
    settings = await mix_ranker_service.settings(session, workspace_id)
    return schemas.WorkspaceRankerRead(
        workspace_id=workspace_id,
        **dataclasses.asdict(settings),
        hidden_ratings=await mix_ranker_service.count(session, workspace_id),
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
            ensure_workspace_permission(user, ws_id, "team", "read")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            cfg = await balancer_admin_service.get_tournament_config(session, node_id)
            return serialize_tournament_config(cfg) if cfg is not None else None

        return await c.envelope(logger, "admin.tournament_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.tournament_config_upsert")
    async def _tournament_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            body = schemas.BalancerTournamentConfigUpsert.model_validate(c.payload(data))
            cfg = await balancer_admin_service.upsert_tournament_config(
                session, tournament_id, node_id, ws_id, body.config_json, user
            )
            return serialize_tournament_config(cfg)

        return await c.envelope(logger, "admin.tournament_config_upsert", op, session_factory=_SF)

    # --- tournament summary (balancer tool context) -------------------------
    @broker.subscriber("rpc.balancer.admin.tournament_summary_get")
    async def _tournament_summary_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "read")
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
            ensure_workspace_permission(user, ws_id, "team", "read")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            balance = await balancer_admin_service.get_balance(session, node_id)
            return serialize_balance(balance) if balance is not None else None

        return await c.envelope(logger, "admin.balance_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_save")
    async def _balance_save(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            body = schemas.BalanceSaveRequest.model_validate(c.payload(data))
            balance = await balancer_admin_service.save_balance(session, tournament_id, node_id, body, user)
            return serialize_balance(balance, already_normalized=True)

        return await c.envelope(logger, "admin.balance_save", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_export")
    async def _balance_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            balance_id = c.require_id(data)
            ws_id = await _get_balance_workspace_id(session, balance_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            # Materialization rewrites tournament.team/player/standing wholesale,
            # so it is metered like the other expensive balancer paths.
            await quota.charge(user, "balancer.balance_export", workspace_id=ws_id)
            balance, removed_teams, imported_teams, advisories = await balancer_admin_service.export_balance(
                session, balance_id, actor_user_id=user.id
            )
            await session.commit()
            return schemas.BalanceExportResponse(
                success=True,
                removed_teams=removed_teams,
                imported_teams=imported_teams,
                balance_id=balance.id,
                advisories=advisories,
            )

        return await c.envelope(logger, "admin.balance_export", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.balance_ranks_export")
    async def _balance_ranks_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            balance_id = c.require_id(data)
            ws_id = await _get_balance_workspace_id(session, balance_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            await quota.charge(user, "balancer.balance_ranks_export", workspace_id=ws_id)
            balance, updated = await balancer_admin_service.export_balance_ranks(
                session, balance_id, actor_user_id=user.id
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
            ensure_workspace_permission(user, workspace_id, "workspace", "read")
            await _ensure_workspace_exists(session, workspace_id)
            cfg = await balancer_admin_service.get_workspace_balancer_config(session, workspace_id)
            return _config_to_read(cfg, workspace_id)

        return await c.envelope(logger, "admin.workspace_config_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.workspace_config_upsert")
    async def _workspace_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        """Pool knobs need ``team.update``; moving the mix channel or the voice setup needs ``workspace.update``.

        Both live in one config blob, so the admin gate applies only when the channel or the voice setup actually
        moves: an organizer who may build teams can save the rank-delta threshold beside an unchanged channel.
        A newly set Discord id must be a channel of the workspace's guild, asked of discord-service.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            ensure_workspace_permission(user, workspace_id, "team", "update")
            await _ensure_workspace_exists(session, workspace_id)
            body = schemas.WorkspaceBalancerConfigUpsert.model_validate(c.payload(data))
            stored = await balancer_admin_service.get_workspace_balancer_config(session, workspace_id)
            voice = (body.mix_voice_category_id, body.mix_general_voice_channel_ids)
            if body.mix_discord_channel_id != _stored_mix_channel(stored) or voice != _stored_voice(stored):
                ensure_workspace_permission(user, workspace_id, "workspace", "update")
            cfg = await balancer_admin_service.upsert_workspace_balancer_config(
                session,
                workspace_id=workspace_id,
                rank_delta_threshold=body.rank_delta_threshold,
                rank_delta_hide_from_pool=body.rank_delta_hide_from_pool,
                mix_discord_channel_id=body.mix_discord_channel_id,
                mix_voice_category_id=body.mix_voice_category_id,
                mix_general_voice_channel_ids=body.mix_general_voice_channel_ids,
                updated_by=user.id,
                list_channels=DiscordClient(broker=broker).guild_channels,
            )
            return _config_to_read(cfg, workspace_id)

        return await c.envelope(logger, "admin.workspace_config_upsert", op, session_factory=_SF)

    # --- workspace mix ranker ----------------------------------------------
    # Same gates as the workspace config above: reading needs workspace.read,
    # anything that moves ratings needs team.update.
    @broker.subscriber("rpc.balancer.admin.workspace_ranker_get")
    async def _workspace_ranker_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            ensure_workspace_permission(user, workspace_id, "workspace", "read")
            await _ensure_workspace_exists(session, workspace_id)
            return await _ranker_read(session, workspace_id)

        return await c.envelope(logger, "admin.workspace_ranker_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.workspace_ranker_upsert")
    async def _workspace_ranker_upsert(data: dict, msg: RabbitMessage) -> dict:
        """Saving a new hidden scale rebuilds every hidden rating before answering."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            ensure_workspace_permission(user, workspace_id, "team", "update")
            await _ensure_workspace_exists(session, workspace_id)
            body = schemas.WorkspaceRankerUpsert.model_validate(c.payload(data))
            await mix_ranker_service.save_settings(
                session,
                workspace_id=workspace_id,
                settings=settings_from_json(body.model_dump()),
                updated_by=user.id,
            )
            await session.commit()
            return await _ranker_read(session, workspace_id)

        return await c.envelope(logger, "admin.workspace_ranker_upsert", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.admin.workspace_ranker_rebuild")
    async def _workspace_ranker_rebuild(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            c.require_admin_panel(user)
            workspace_id = c.require_id(data)
            ensure_workspace_permission(user, workspace_id, "team", "update")
            await _ensure_workspace_exists(session, workspace_id)
            matches, hidden_ratings = await mix_ranker_service.rebuild(session, workspace_id)
            await session.commit()
            return schemas.WorkspaceRankerRebuildRead(matches=matches, hidden_ratings=hidden_ratings)

        return await c.envelope(logger, "admin.workspace_ranker_rebuild", op, session_factory=_SF)
