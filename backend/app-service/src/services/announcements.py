"""Operator writes for announcements: the only place a human authors a
notification row.

Everything about an announcement *as a notification* -- the payload shape, the
locale rules, the audience/column agreement -- belongs to
``shared.services.notifications``; this module owns the operator half: which row
an operator is allowed to reach, how an edit merges into the stored snapshot,
what "delete" means, and the audit entry that has to land in the same
transaction as the write (Global Constraint 6).

Delete is an expiry, not a ``DELETE``. ``notification_read`` references the id
with no foreign key (the journal convention this table follows), so removing the
row would leave read marks nothing will ever collect, and would point the audit
entry at an id that resolves to nothing. Setting ``expires_at`` retires the
announcement through the same time window every read already filters on, and
keeps "who saw this" answerable afterwards.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.repository.notification import NotificationRepository
from shared.services.audit import record_admin_audit
from shared.services.notifications import notify, validate_notification_payload
from src import schemas

__all__ = ("ANNOUNCEMENT_KIND", "create", "get", "list_for_scope", "retire", "update")

ANNOUNCEMENT_KIND = "announcement.published"

_notifications = NotificationRepository()

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def _label(payload: dict[str, Any]) -> str | None:
    """The title an operator would recognise in the audit feed.

    Stored per locale, so the default one is the only non-arbitrary pick.
    """
    locale = payload.get("default_locale")
    entry = (payload.get("locales") or {}).get(locale) or {}
    return entry.get("title")


async def list_for_scope(
    session: AsyncSession,
    *,
    workspace_id: int | None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[schemas.NotificationItem]:
    """One scope's announcements, newest first, expired ones included.

    Unlike the inbox this is not filtered by the time window: an operator's list
    exists to show what is scheduled and what has been retired, which is exactly
    what the window hides. ``workspace_id=None`` is the platform-wide feed and is
    reachable only for a superuser -- see ``rpc.announcements._scope``.
    """
    model = models.Notification
    scope = (
        model.audience == "global"
        if workspace_id is None
        else sa.and_(model.audience == "workspace", model.workspace_id == workspace_id)
    )
    result = await session.execute(
        sa.select(model)
        .where(model.kind == ANNOUNCEMENT_KIND, scope)
        .order_by(model.published_at.desc(), model.id.desc())
        .limit(max(1, min(int(limit), MAX_LIST_LIMIT))),
    )
    return [schemas.NotificationItem.model_validate(row) for row in result.scalars().all()]


async def get(session: AsyncSession, announcement_id: int) -> models.Notification:
    """Load one announcement, or 404.

    The kind check is what keeps this CRUD off the system notifications: ids are
    shared across every audience, so without it an operator could edit the text
    of somebody's team invite or retire it out of their inbox.
    """
    row = await _notifications.get(session, announcement_id)
    if row is None or row.kind != ANNOUNCEMENT_KIND or row.audience == "user":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    return row


async def create(
    session: AsyncSession,
    *,
    actor: AuthUser,
    data: dict[str, Any],
    body: schemas.AnnouncementCreate,
) -> schemas.NotificationItem:
    row = await notify(
        session,
        kind=ANNOUNCEMENT_KIND,
        payload=body.payload(),
        audience=body.audience,
        workspace_id=body.workspace_id,
        actor_auth_user_id=actor.id,
        published_at=body.published_at,
        expires_at=body.expires_at,
    )
    # The id and the server-stamped ``published_at`` both come from the INSERT,
    # and the audit row below needs the id.
    await session.flush()
    await session.refresh(row)

    await record_admin_audit(
        session,
        action="announcement.create",
        actor=actor,
        data=data,
        workspace_id=row.workspace_id,
        entity_type="announcement",
        entity_id=row.id,
        entity_label=_label(row.payload_json),
        after=row.payload_json,
    )
    item = schemas.NotificationItem.model_validate(row)
    await session.commit()
    return item


async def update(
    session: AsyncSession,
    *,
    actor: AuthUser,
    data: dict[str, Any],
    row: models.Notification,
    body: schemas.AnnouncementUpdate,
) -> schemas.NotificationItem:
    """Edit the text (and the expiry) of an announcement that is already out.

    Read marks are untouched on purpose: the mark is the dismissal, so clearing
    it would re-show a platform-wide banner to everyone who already closed it --
    for a corrected typo.
    """
    before = dict(row.payload_json)
    validated = validate_notification_payload(
        ANNOUNCEMENT_KIND,
        {**before, **body.changes()},
        audience=row.audience,
    )
    # JSONB does not track in-place mutation -- reassign.
    row.payload_json = validated.model_dump(mode="json", exclude_none=True)
    if "expires_at" in body.model_fields_set:
        row.expires_at = body.expires_at

    await record_admin_audit(
        session,
        action="announcement.update",
        actor=actor,
        data=data,
        workspace_id=row.workspace_id,
        entity_type="announcement",
        entity_id=row.id,
        entity_label=_label(row.payload_json),
        before=before,
        after=row.payload_json,
    )
    item = schemas.NotificationItem.model_validate(row)
    await session.commit()
    return item


async def retire(
    session: AsyncSession,
    *,
    actor: AuthUser,
    data: dict[str, Any],
    row: models.Notification,
) -> schemas.NotificationItem:
    """ "Delete": expire it now -- see the module docstring for why not a DELETE."""
    before = {"expires_at": row.expires_at.isoformat() if row.expires_at else None}
    # ``func.now()`` rather than a Python timestamp: the same transaction clock
    # the rows are stamped with, so the row is never "expired in the future".
    row.expires_at = sa.func.now()
    await session.flush()
    await session.refresh(row, ["expires_at"])

    await record_admin_audit(
        session,
        action="announcement.delete",
        actor=actor,
        data=data,
        workspace_id=row.workspace_id,
        entity_type="announcement",
        entity_id=row.id,
        entity_label=_label(row.payload_json),
        before=before,
        after={"expires_at": row.expires_at.isoformat() if row.expires_at else None},
    )
    item = schemas.NotificationItem.model_validate(row)
    await session.commit()
    return item
