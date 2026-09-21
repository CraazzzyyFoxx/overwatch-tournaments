"""Operator reads and retirement for the notifications one workspace produced.

The scope is ``notification.source_workspace_id`` -- the tenant whose activity
*caused* the row -- and never ``workspace_id``, which is an audience target and
is null on every personal row. That distinction is the whole point of the
screen: a registration decision is addressed to one competitor and owned by the
organizer that decided it.

Two rules hold this surface together:

* **Announcements are not reachable here.** They have their own CRUD
  (``services/announcements.py``) with its own locale rules and its own
  permission; listing them in both places would offer two different delete
  buttons for one row. ``announcement.published`` is filtered out of every
  statement below, the mirror image of the kind check ``announcements.get``
  does.
* **"Delete" is a retire, exactly as it is for announcements.** ``expires_at =
  now()`` takes the row out of every recipient's inbox and out of the badge
  count, while the row and its read marks survive: ``notification_read`` points
  at the id with no foreign key, and the journal is append-only. A ``DELETE``
  would also silently discard the per-viewer ``deleted_at`` history.

An operator can retire an explicit selection (``ids``) or a whole kind
(``kind``), but never "everything": a call that names neither is a 422 rather
than a tenant-wide wipe one mis-click away.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.repository.notification import (
    InvalidCursorError,
    NotificationRepository,
    decode_cursor,
    encode_cursor,
)
from shared.services.audit import record_admin_audit
from shared.services.notifications import NOTIFICATION_KINDS
from src import schemas
from src.services.announcements import ANNOUNCEMENT_KIND

__all__ = ("DEFAULT_LIST_LIMIT", "MAX_LIST_LIMIT", "SYSTEM_KINDS", "list_for_workspace", "retire")

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200

_notifications = NotificationRepository()

#: Every kind an operator can see here: the registry minus the announcement,
#: which owns a different screen. Derived rather than restated, so a sixth kind
#: is listable the moment it exists.
SYSTEM_KINDS: tuple[str, ...] = tuple(kind for kind in NOTIFICATION_KINDS if kind != ANNOUNCEMENT_KIND)


def _scope(workspace_id: int) -> list[sa.ColumnElement[bool]]:
    model = models.Notification
    return [model.source_workspace_id == workspace_id, model.kind != ANNOUNCEMENT_KIND]


def _validated_kind(kind: str | None) -> str | None:
    if kind is None:
        return None
    if kind not in SYSTEM_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown kind: {kind}")
    return kind


async def list_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: int,
    kind: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> schemas.NotificationAdminPage:
    """One tenant's produced notifications, newest first, keyset-paginated.

    Unfiltered by the time window, like the announcement list and for the same
    reason: an operator screen exists to show what is scheduled and what has
    already been retired, which the inbox's window hides.

    The cursor is the inbox's own ``(published_at, id)`` encoding -- same order,
    same tie-breaking, so the helper is shared rather than re-derived.

    The recipient join is a strict LEFT OUTER, for the reason the audit feed
    states: ``recipient_auth_user_id`` carries no foreign key by design, so the
    account may be gone, and an INNER join would hide exactly the rows an
    operator still has to retire.
    """
    model = models.Notification
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    query = (
        sa.select(model, AuthUser.username)
        .outerjoin(AuthUser, AuthUser.id == model.recipient_auth_user_id)
        .where(*_scope(workspace_id))
    )
    if kind is not None:
        query = query.where(model.kind == _validated_kind(kind))
    if cursor is not None:
        try:
            after_published_at, after_id = decode_cursor(cursor)
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail="Invalid notification page cursor") from exc
        query = query.where(
            sa.tuple_(model.published_at, model.id)
            < sa.tuple_(
                sa.literal(after_published_at, model.published_at.type),
                sa.literal(after_id, model.id.type),
            ),
        )

    # One row past the page, the same "is there more" trick the inbox uses.
    rows = (await session.execute(query.order_by(model.published_at.desc(), model.id.desc()).limit(limit + 1))).all()
    next_cursor = encode_cursor(rows[limit - 1][0]) if len(rows) > limit else None
    return schemas.NotificationAdminPage(
        items=[
            schemas.NotificationAdminItem.model_validate(row).model_copy(update={"recipient_username": username})
            for row, username in rows[:limit]
        ],
        next_cursor=next_cursor,
    )


async def retire(
    session: AsyncSession,
    *,
    actor: AuthUser,
    data: dict[str, Any],
    workspace_id: int,
    ids: list[int] | None = None,
    kind: str | None = None,
) -> schemas.NotificationRetireResult:
    """Expire the selected rows as of now, and audit the whole batch once.

    ``ids`` and ``kind`` are both filters over the same scoped statement, so an
    id belonging to another tenant contributes nothing instead of erroring --
    the same non-oracle rule the inbox's own writes follow. Already-expired rows
    are skipped rather than re-stamped, which makes a repeat call answer 0 and
    keeps the original retirement time.
    """
    if not ids and kind is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name the notifications to retire: ids, a kind, or both",
        )

    model = models.Notification
    conditions = [*_scope(workspace_id), sa.or_(model.expires_at.is_(None), model.expires_at > sa.func.now())]
    if kind is not None:
        conditions.append(model.kind == _validated_kind(kind))
    if ids:
        conditions.append(model.id.in_({int(value) for value in ids}))

    retired = await _notifications.retire(session, filters=conditions)

    await record_admin_audit(
        session,
        action="notification.delete",
        actor=actor,
        data=data,
        workspace_id=workspace_id,
        entity_type="notification",
        # A batch has no single entity; the filter that selected it is the fact
        # worth keeping, and it lives in ``after`` beside the resulting count.
        entity_id=int(ids[0]) if ids and len(ids) == 1 else None,
        entity_label=kind,
        after={"kind": kind, "ids": sorted(int(value) for value in ids) if ids else None, "retired": retired},
    )
    await session.commit()
    return schemas.NotificationRetireResult(retired=retired)
