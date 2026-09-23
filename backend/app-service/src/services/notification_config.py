"""A workspace's notification delivery settings: read, and write with checks.

One row, three values (channel, locale, which kinds), and one rule worth the
module: **the channel must belong to this workspace's own verified guild**.
Without that check an administrator of workspace A could point the bot at a
channel in guild B -- the bot is in both, so Discord itself would allow it --
and make the platform post into a server they do not administer.

The guild lookup arrives as a callable rather than a ``DiscordClient``: the
client needs the broker, which is a transport concern the RPC layer already
holds, and this way the rule is testable without one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from shared.repository.notification import NotificationWorkspaceConfigRepository
from shared.services.notifications import BROADCASTABLE_KINDS
from shared.services.subscriptions.providers.discord_role import DiscordError
from src import schemas

__all__ = ("DEFAULT_BROADCAST_KINDS", "read_config", "repository", "write_config")

repository = NotificationWorkspaceConfigRepository()

#: What a workspace broadcasts before anybody configures it -- mirrors the
#: column's server default, for the read that has no row yet.
DEFAULT_BROADCAST_KINDS = ["registration.opened", "check_in.opened"]

#: Sorted once: the checkbox list the settings screen renders.
_BROADCASTABLE = sorted(BROADCASTABLE_KINDS)

ChannelReader = Callable[[str], Awaitable[list[dict[str, Any]]]]


def _read(workspace: Any, stored: Any) -> schemas.NotificationWorkspaceConfigRead:
    """The response shape, from the workspace plus its config row (or no row)."""
    return schemas.NotificationWorkspaceConfigRead(
        workspace_id=workspace.id,
        discord_guild_id=workspace.discord_guild_id,
        discord_channel_id=(
            str(stored.discord_channel_id) if stored is not None and stored.discord_channel_id is not None else None
        ),
        locale=stored.locale if stored is not None else "ru",
        broadcast_kinds=list(stored.broadcast_kinds or []) if stored is not None else list(DEFAULT_BROADCAST_KINDS),
        broadcastable_kinds=list(_BROADCASTABLE),
    )


async def read_config(session: Any, workspace: Any) -> schemas.NotificationWorkspaceConfigRead:
    """Settings as stored, or the defaults a workspace starts on."""
    stored = await repository.for_workspace(session, workspace.id)
    return _read(workspace, stored)


async def write_config(
    session: Any,
    workspace: Any,
    body: schemas.NotificationWorkspaceConfigUpdate,
    *,
    list_channels: ChannelReader,
) -> schemas.NotificationWorkspaceConfigRead:
    """Store the settings after proving the channel is this workspace's to use.

    The locale and the kind list are validated by the schema; only the channel
    needs Discord. An unreachable Discord is a 503, never a silent accept: a
    stored channel that was never checked is exactly the cross-guild post this
    module exists to prevent.
    """
    channel_id: int | None = None
    if body.discord_channel_id is not None:
        guild_id = workspace.discord_guild_id
        if not guild_id:
            raise HTTPException(status_code=409, detail="discord_guild_not_linked")
        try:
            channels = await list_channels(str(guild_id))
        except DiscordError as exc:
            raise HTTPException(status_code=503, detail="discord_unavailable") from exc
        # ``guild_channels`` already answers with text channels only, ids as
        # strings -- the same list the picker renders.
        if body.discord_channel_id not in {str(channel.get("id")) for channel in channels}:
            raise HTTPException(status_code=422, detail="discord_channel_not_in_guild")
        channel_id = int(body.discord_channel_id)

    stored = await repository.upsert(
        session,
        workspace_id=workspace.id,
        discord_channel_id=channel_id,
        locale=body.locale,
        broadcast_kinds=list(body.broadcast_kinds),
    )
    await session.commit()
    return _read(workspace, stored)
