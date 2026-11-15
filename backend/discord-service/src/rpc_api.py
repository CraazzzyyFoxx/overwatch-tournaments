"""``rpc.discord.*``: what the site asks the bot itself, through the gateway.

The gateway injects the caller's identity, exactly as for any other service's
typed RPC; every handler gates on it (``shared.rpc.common``) before touching
Discord or the database.

- ``workspace_roles|workspace_channels|workspace_guild``: the linked guild of a
  workspace, read from the gateway cache (``DiscordDirectoryService``), for the
  workspace settings pickers. A picker with no options is the right answer for
  an unreachable guild -- these never 500 on Discord, they carry ``error``.
- ``channel.get|upsert|backfill|delete``: the tournament's match-log channel.
  A write reloads the channel registry in-process, so the bot starts or stops
  watching at once; ``backfill`` rescans the channel's history in the background.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import discord
from faststream.rabbit import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.rbac.workspace_lookup import get_tournament_workspace_id
from shared.repository import DiscordChannelRepository, WorkspaceRepository
from shared.rpc import common as c
from shared.rpc.identity import ensure_workspace_permission
from src import schemas
from src.services.channel_registry import ChannelRegistry
from src.services.directory import DirectoryOutcome, DiscordDirectoryService

__all__ = ("BACKFILL_LIMIT", "register")

#: How far back a manual backfill walks a channel, newest first.
BACKFILL_LIMIT = 500

_channels = DiscordChannelRepository()
_workspaces = WorkspaceRepository()

#: The guild card of a workspace with no guild linked.
_NO_GUILD: dict[str, Any] = {
    "connected": False,
    "name": None,
    "icon_url": None,
    "member_count": 0,
    "owner_id": None,
    "owner_name": None,
    "owner_avatar_url": None,
}

#: Running backfills: ``create_task`` keeps only a weak reference.
_backfills: set[asyncio.Task[None]] = set()


async def _gate_workspace(session: AsyncSession, data: dict[str, Any]) -> models.Workspace:
    """The workspace named by the path, once the caller may administer it."""
    workspace_id = c.require_path_int(data, "workspace_id")
    user = c.actor(data)
    c.require_active(user)
    ensure_workspace_permission(user, workspace_id, "workspace", "update")
    workspace = await _workspaces.get(session, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _gate_tournament(session: AsyncSession, data: dict[str, Any], action: str) -> tuple[int, int]:
    """``(tournament_id, workspace_id)`` once the caller holds ``discord_channel.<action>`` there."""
    user = c.actor(data)
    c.require_active(user)
    tournament_id = c.require_id(data)
    # Also the tournament's existence check (404).
    workspace_id = await get_tournament_workspace_id(session, tournament_id)
    ensure_workspace_permission(user, workspace_id, "discord_channel", action)
    return tournament_id, workspace_id


async def _guild_text_channel(bot: discord.Client, guild_id: str | None, raw_channel_id: str) -> int:
    """The id of ``raw_channel_id`` once it is a text channel of ``guild_id``.

    A channel of another guild would have the bot read logs into this
    workspace's tournament from a server it does not own.
    """
    if not guild_id:
        raise HTTPException(status_code=409, detail="discord_guild_not_linked")
    if not raw_channel_id.isdigit():
        raise HTTPException(status_code=422, detail="discord_channel_not_in_guild")
    channel_id = int(raw_channel_id)
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound, discord.Forbidden:
            channel = None
        except discord.HTTPException as exc:
            raise HTTPException(status_code=503, detail="discord_unavailable") from exc
    if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != guild_id:
        raise HTTPException(status_code=422, detail="discord_channel_not_in_guild")
    return channel_id


def register(
    broker: Any,
    *,
    bot: discord.Client,
    registry: ChannelRegistry,
    directory: DiscordDirectoryService,
    session_maker: Callable[[], Any],
    logger: Any,
) -> None:
    async def run(label: str, op: Callable[[AsyncSession], Awaitable[Any]]) -> dict[str, Any]:
        await bot.wait_until_ready()
        return await c.envelope(logger, label, op, session_factory=session_maker, service="discord")

    async def guild_read(
        data: dict[str, Any],
        label: str,
        read: Callable[[str], Awaitable[DirectoryOutcome]],
        unlinked: dict[str, Any],
    ) -> dict[str, Any]:
        """One gated read of a workspace's guild; the directory's failure body is the degraded answer."""

        async def op(session: AsyncSession) -> dict[str, Any]:
            workspace = await _gate_workspace(session, data)
            guild_id = workspace.discord_guild_id
            if not guild_id:
                return {"guild_id": None, **unlinked}
            outcome = await read(guild_id)
            if outcome.status != "success":
                logger.warning(f"{label} failed for workspace {workspace.id}: {outcome.payload.get('error')}")
            return outcome.payload

        return await run(label, op)

    # ── a workspace's linked guild (workspace.update) ────────────────────────
    @broker.subscriber("rpc.discord.workspace_roles")
    async def workspace_roles(data: dict, msg: RabbitMessage) -> dict:
        return await guild_read(data, "workspace_roles", directory.get_guild_roles, {"roles": []})

    @broker.subscriber("rpc.discord.workspace_channels")
    async def workspace_channels(data: dict, msg: RabbitMessage) -> dict:
        return await guild_read(data, "workspace_channels", directory.get_guild_channels, {"channels": []})

    @broker.subscriber("rpc.discord.workspace_guild")
    async def workspace_guild(data: dict, msg: RabbitMessage) -> dict:
        return await guild_read(data, "workspace_guild", directory.get_guild_info, _NO_GUILD)

    # ── a tournament's match-log channel (discord_channel.*) ─────────────────
    @broker.subscriber("rpc.discord.channel.get")
    async def channel_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: AsyncSession) -> schemas.DiscordChannelRead | None:
            tournament_id, _ = await _gate_tournament(session, data, "read")
            row = await _channels.get_by_tournament(session, tournament_id)
            return schemas.DiscordChannelRead.model_validate(row) if row else None

        return await run("channel.get", op)

    @broker.subscriber("rpc.discord.channel.upsert")
    async def channel_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: AsyncSession) -> schemas.DiscordChannelRead:
            tournament_id, workspace_id = await _gate_tournament(session, data, "update")
            body = schemas.DiscordChannelUpsert.model_validate(c.payload(data))
            workspace = await _workspaces.get(session, workspace_id)
            channel_id = await _guild_text_channel(bot, workspace.discord_guild_id, body.channel_id)

            fields: dict[str, Any] = {
                "channel_id": channel_id,
                "channel_name": body.channel_name,
                "is_active": body.is_active,
            }
            row = await _channels.get_by_tournament(session, tournament_id)
            if row is None:
                # Every NOT NULL column is set before ``create`` flushes.
                row = await _channels.create(
                    session, models.TournamentDiscordChannel(tournament_id=tournament_id, **fields)
                )
            else:
                if row.channel_id != channel_id:
                    # Another channel's cursor would skip this one's history.
                    fields["last_scanned_message_id"] = None
                row = await _channels.update_fields(session, row, fields)
            await session.commit()
            await session.refresh(row)
            await registry.reload()
            return schemas.DiscordChannelRead.model_validate(row)

        return await run("channel.upsert", op)

    @broker.subscriber("rpc.discord.channel.backfill")
    async def channel_backfill(data: dict, msg: RabbitMessage) -> dict:
        # For a workspace that just bound a channel already holding match logs:
        # the reconnect rescan only reads past the cursor, this reads the history.
        async def op(session: AsyncSession) -> dict[str, str]:
            tournament_id, _ = await _gate_tournament(session, data, "update")
            row = await _channels.get_by_tournament(session, tournament_id)
            if row is None or not row.is_active:
                raise HTTPException(status_code=404, detail="Discord channel not configured")
            task = asyncio.create_task(
                bot.attachment_processor.process_channel_history(row.channel_id, tournament_id, limit=BACKFILL_LIMIT)
            )
            _backfills.add(task)
            task.add_done_callback(_backfills.discard)
            return {"message": "Backfill started: scanning channel history for match logs"}

        return await run("channel.backfill", op)

    @broker.subscriber("rpc.discord.channel.delete")
    async def channel_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: AsyncSession) -> None:
            tournament_id, _ = await _gate_tournament(session, data, "delete")
            row = await _channels.get_by_tournament(session, tournament_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Discord channel not configured")
            await _channels.delete(session, row)
            await session.commit()
            await registry.reload()

        return await run("channel.delete", op)
