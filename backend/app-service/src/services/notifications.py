"""Inbox reads for the app worker: the membership set, then the repository.

The repository owns the audience predicate but deliberately takes
``workspace_ids`` as a parameter (see its module docstring). Resolving that set
is this module's whole job, and it is a union of two different notions of
"belongs to this workspace":

* the **roster** -- ``workspace_member.player_id -> players.user.auth_user_id``,
  the players a workspace balances from; and
* the **RBAC role holders** -- accounts holding a role scoped to the workspace,
  the predicate ``shared/services/workspace_roster.py:workspace_member_user_ids``
  answers.

Both halves are required and neither implies the other: a player with no role
would miss their own workspace's announcements, and a host who never played
would miss the ones they are responsible for. ``workspace_member_user_ids`` is
not called here because its question is the inverse of this one -- it answers
"which of these *users* belong to workspace X", so reusing it would mean one
query per candidate workspace. The RBAC half below is its ``holds_workspace_role``
exists-clause, turned around into a single UNION with the roster half.

The superuser bypass that function applies is deliberately *not* mirrored: an
inbox is personal, not an admin surface, and expanding it to every workspace
on the platform would bury a superuser's own notifications under every
workspace announcement ever published.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from cashews import cache

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository.notification import (
    DEFAULT_PAGE_LIMIT,
    InvalidCursorError,
    NotificationPreferenceRepository,
    NotificationRepository,
)
from shared.services.notifications import effective_discord_dm
from shared.services.subscriptions.strategies import load_provider_user_ids
from src import schemas

__all__ = (
    "WORKSPACE_IDS_CACHE_KEY",
    "WORKSPACE_IDS_CACHE_TTL",
    "active_announcements",
    "delete",
    "inbox_page",
    "mark_read",
    "preferences",
    "update_preferences",
    "workspace_ids_for",
)

logger = logging.getLogger(__name__)

repository = NotificationRepository()
preference_repository = NotificationPreferenceRepository()

# 60 s: the set changes when somebody joins a workspace or is granted a role,
# and a minute of staleness on "which announcements do I see" is invisible,
# while the two queries run on every inbox open, every mark-read and every
# badge refetch of every connected client.
WORKSPACE_IDS_CACHE_TTL = 60
WORKSPACE_IDS_CACHE_KEY = "backend:notifications:workspace_ids:{auth_user_id}"


async def _query_workspace_ids(session: Any, auth_user_id: int) -> tuple[int, ...]:
    """Roster ∪ RBAC role holders, as one UNION -- see the module docstring."""
    roster = (
        sa.select(models.WorkspaceMember.workspace_id)
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(models.User.auth_user_id == auth_user_id)
    )
    rbac = (
        sa.select(models.Role.workspace_id)
        .join(models.user_roles, models.user_roles.c.role_id == models.Role.id)
        .where(
            models.user_roles.c.user_id == auth_user_id,
            models.Role.workspace_id.is_not(None),
        )
    )
    result = await session.execute(sa.union(roster, rbac))
    return tuple(sorted(row[0] for row in result.all() if row[0] is not None))


async def workspace_ids_for(session: Any, *, auth_user_id: int) -> tuple[int, ...]:
    """The workspaces whose announcements this identity may see, cached 60 s.

    A Redis outage degrades this to two extra queries per read, never to an
    error and never to an empty set: returning ``()`` on a cache miss would
    silently hide every workspace announcement from everybody.
    """
    key = WORKSPACE_IDS_CACHE_KEY.format(auth_user_id=auth_user_id)
    try:
        cached = await cache.get(key)
    except Exception:  # noqa: BLE001 - cache backend down: fall through to the query
        logger.warning("notification workspace-id cache unreadable; recomputing", exc_info=True)
        cached = None
    if cached is not None:
        return tuple(cached)

    workspace_ids = await _query_workspace_ids(session, auth_user_id)
    try:
        await cache.set(key, list(workspace_ids), expire=WORKSPACE_IDS_CACHE_TTL)
    except Exception:  # noqa: BLE001 - the answer is already computed; caching is best-effort
        logger.warning("notification workspace-id cache unwritable", exc_info=True)
    return workspace_ids


async def inbox_page(
    session: Any,
    *,
    auth_user_id: int,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> schemas.NotificationInboxRead:
    workspace_ids = await workspace_ids_for(session, auth_user_id=auth_user_id)
    try:
        page = await repository.page(
            session,
            auth_user_id=auth_user_id,
            workspace_ids=workspace_ids,
            cursor=cursor,
            limit=limit,
        )
    except InvalidCursorError as exc:
        # A client error, and it has to *say so*: silently restarting at page
        # one loops a caller that keeps following the cursor it is handed.
        raise HTTPException(status_code=422, detail="Invalid notification page cursor") from exc

    unread_count = await repository.unread_count(session, auth_user_id=auth_user_id, workspace_ids=workspace_ids)
    return schemas.NotificationInboxRead(
        items=[schemas.NotificationItem.model_validate(row) for row in page.items],
        unread_count=unread_count,
        next_cursor=page.next_cursor,
    )


async def mark_read(
    session: Any,
    *,
    auth_user_id: int,
    notification_ids: Sequence[int] | None = None,
) -> schemas.NotificationMarkReadResult:
    """Insert read marks, then report the badge count the client should show.

    ``notification_ids=None`` marks the whole visible inbox. Ids the caller may
    not see are dropped inside the repository's SELECT, so a foreign id is
    indistinguishable from one that never existed.
    """
    workspace_ids = await workspace_ids_for(session, auth_user_id=auth_user_id)
    marked = await repository.mark_read(
        session,
        auth_user_id=auth_user_id,
        workspace_ids=workspace_ids,
        notification_ids=notification_ids,
    )
    await session.commit()
    unread_count = await repository.unread_count(session, auth_user_id=auth_user_id, workspace_ids=workspace_ids)
    return schemas.NotificationMarkReadResult(marked=marked, unread_count=unread_count)


async def delete(
    session: Any,
    *,
    auth_user_id: int,
    notification_ids: Sequence[int] | None = None,
    only_read: bool = False,
) -> schemas.NotificationDeleteResult:
    """Drop rows from this caller's inbox, then report the refreshed badge.

    A deletion is per viewer -- the ``notification`` row survives, because one
    announcement sits in every inbox and the journal is append-only. Ids the
    caller may not see are dropped inside the repository's SELECT, so a foreign
    id is indistinguishable from one that never existed.
    """
    workspace_ids = await workspace_ids_for(session, auth_user_id=auth_user_id)
    deleted = await repository.delete(
        session,
        auth_user_id=auth_user_id,
        workspace_ids=workspace_ids,
        notification_ids=notification_ids,
        only_read=only_read,
    )
    await session.commit()
    unread_count = await repository.unread_count(session, auth_user_id=auth_user_id, workspace_ids=workspace_ids)
    return schemas.NotificationDeleteResult(deleted=deleted, unread_count=unread_count)


async def active_announcements(session: Any, *, auth_user_id: int | None = None) -> list[schemas.NotificationItem]:
    """Platform-wide announcements for the banner; dismissed ones drop out.

    Anonymous callers reach ``active_global`` with no identity at all: no
    membership lookup, no workspace rows, nothing host-dependent -- which is
    what makes the gateway's shared anonymous response cache safe.
    """
    rows = await repository.active_global(session, auth_user_id=auth_user_id)
    return [schemas.NotificationItem.model_validate(row) for row in rows]


async def preferences(session: Any, *, auth_user_id: int) -> schemas.NotificationPreferencesRead:
    """This caller's Discord-DM switches, with the defaults filled in.

    ``discord_linked`` rides along because the switches are inert without a
    connected account: a settings page that offers three toggles and delivers
    nothing is the bug this field prevents.
    """
    stored = await preference_repository.stored_discord_dm(session, auth_user_id)
    linked = await load_provider_user_ids(session, auth_user_ids=[auth_user_id], oauth_provider="discord")
    return schemas.NotificationPreferencesRead(
        discord_dm=schemas.NotificationDmGroups(**effective_discord_dm(stored)),
        discord_linked=bool(linked.get(auth_user_id)),
    )


async def update_preferences(
    session: Any,
    *,
    auth_user_id: int,
    discord_dm: dict[str, bool],
) -> schemas.NotificationPreferencesRead:
    """Merge a partial edit into the stored switches and answer with the effect.

    Partial rather than replacing: the row holds only what the user changed, so
    a group added upstream stays on its default for everybody until they touch
    it -- and one toggle flipped in a stale tab cannot silently re-assert the
    other two.
    """
    stored = await preference_repository.stored_discord_dm(session, auth_user_id)
    stored.update(discord_dm)
    await preference_repository.set_discord_dm(session, auth_user_id=auth_user_id, discord_dm=stored)
    await session.commit()
    return await preferences(session, auth_user_id=auth_user_id)
