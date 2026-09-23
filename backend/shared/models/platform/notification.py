from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = (
    "Notification",
    "NotificationDelivery",
    "NotificationPreference",
    "NotificationRead",
    "NotificationWorkspaceConfig",
)


class Notification(db.Base):
    """One row per thing a user has to be told, append-only.

    Written by ``shared.services.notifications.notify`` inside the mutating
    transaction, never touched again -- hence ``db.Base`` and not
    ``db.TimeStampIntegerMixin``: an ``updated_at`` here could only ever hold a
    lie, the same reasoning ``AuditLog`` states.

    The table carries NO foreign keys -- the convention ``audit_log``,
    ``event_outbox`` and ``realtime.workspace_event`` already follow, for the
    same reason: an append-only journal has to outlive the business rows it
    talks about. ``ON DELETE CASCADE`` on ``recipient_auth_user_id`` or
    ``workspace_id`` would erase a user's history the moment the referent is
    deleted, and a team invite whose team is gone is exactly the notification
    still worth reading. Readability after the referent disappears comes from
    the ``payload_json`` snapshot, not from a join: the frontend renders
    ``t("notifications.kinds.<kind>", payload)`` and never resolves an id.

    ``published_at`` is separate from ``created_at`` because it is
    *schedulable*: an announcement may be written now and become visible later,
    so the audience predicate filters on ``published_at <= now()`` while
    ``created_at`` stays the immutable "when was this row inserted" fact that
    ordering, debugging and retention need. Collapsing the two would make a
    scheduled announcement either invisible forever or leaked early, depending
    on which meaning won.
    """

    __tablename__ = "notification"
    __table_args__ = (
        # The four constraints keep audience and its target in agreement. A
        # ``user`` row without a recipient is deliverable to nobody; a
        # ``workspace``/``global`` row *with* one is deliverable to one person
        # under a rule written for many -- both are unreachable states the
        # audience predicate has no honest answer for.
        CheckConstraint(
            "audience <> 'user' OR recipient_auth_user_id IS NOT NULL",
            name="ck_notification_user_has_recipient",
        ),
        CheckConstraint(
            "audience = 'user' OR recipient_auth_user_id IS NULL",
            name="ck_notification_non_user_has_no_recipient",
        ),
        CheckConstraint(
            "audience <> 'workspace' OR workspace_id IS NOT NULL",
            name="ck_notification_workspace_has_workspace",
        ),
        CheckConstraint(
            "audience = 'workspace' OR workspace_id IS NULL",
            name="ck_notification_non_workspace_has_no_workspace",
        ),
        # The inbox read: one recipient's feed, newest first.
        Index("ix_notification_recipient_published", "recipient_auth_user_id", text("published_at DESC")),
        # The announcement read: workspace + global rows only. Partial on
        # purpose -- per-user rows are the overwhelming majority of the table
        # and none of them are ever fetched through this prefix, so keeping
        # them out of the index keeps it small enough to stay cached.
        Index(
            "ix_notification_audience_published",
            "audience",
            text("published_at DESC"),
            postgresql_where=text("audience <> 'user'"),
        ),
        # The operator read: one tenant's produced rows, newest first. Partial,
        # like the announcement index above -- rows with no source tenant are
        # never fetched through this prefix.
        Index(
            "ix_notification_source_workspace_published",
            "source_workspace_id",
            text("published_at DESC"),
            postgresql_where=text("source_workspace_id IS NOT NULL"),
        ),
        # ``notify(dedupe_key=...)``'s existence check. Deliberately NOT unique:
        # a unique index would turn two racing status transitions into an
        # ``IntegrityError`` inside ``transition_status``; a rare duplicate row
        # is the cheaper failure.
        Index(
            "ix_notification_dedupe",
            "kind",
            "dedupe_key",
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    # ``user`` | ``workspace`` | ``global``. Plain String, not a Postgres enum:
    # same precedent as ``verification_status``/``newcomer_scope``, so a fourth
    # audience never needs a migration.
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    # Set for ``audience='user'`` only, and always computed server-side from the
    # JWT identity of the flow that triggered the notification.
    recipient_auth_user_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    # Set for ``audience='workspace'`` only.
    workspace_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    # The tenant whose activity *produced* the row, set for every audience
    # including ``user`` -- distinct from ``workspace_id`` above, which is the
    # audience target and only ever set for ``audience='workspace'``. A
    # registration decision is addressed to one person and owned by the
    # organizer whose tournament decided it; without this column a workspace
    # operator cannot see, let alone retire, the notifications their own
    # tournaments emitted. ``NULL`` = produced outside any tenant (a
    # platform-wide announcement) or written before this column existed and not
    # reachable by the backfill.
    source_workspace_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Producer-chosen identity of "the same event" (``tournament:10``,
    # ``encounter:5:<iso>``). ``notify()`` returns the existing row for the
    # same kind + key + recipient instead of writing a second one. NULL = the
    # kind has legitimate repeats (an invite sent again) and is never deduped.
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The render snapshot: named domain fields the frontend interpolates into
    # the ``kind``'s i18n message. No text is stored for system kinds, so a
    # translation fix reaches old rows too.
    # NOTE: JSONB does not track in-place mutation -- always reassign.
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        nullable=False,
        server_default=text("'{}'"),
    )
    # NULL = machine actor (scheduler, cascade), the same way ``audit_log``
    # tells a system-triggered row apart from a human-triggered one.
    actor_auth_user_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # NULL = never expires. Announcements use it to retire themselves without
    # an operator having to come back and delete the row.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NotificationRead(db.Base):
    """Per-viewer state for one notification: read, and/or deleted.

    Keyed by ``(auth_user_id, notification_id)`` rather than a surrogate id --
    the pair *is* the identity, and the composite primary key makes
    "mark read" idempotent in the database instead of in every caller.

    ``deleted_at`` is the inbox's delete button. It lives here and not on
    ``Notification`` because dismissal is a fact about the *pair*: one row can
    be a platform-wide announcement sitting in thousands of inboxes, and one
    reader throwing it away must not take it out of the others'. The journal
    itself stays append-only (``expires_at`` is the operator's "retire it for
    everyone", a different verb with a different audience).

    No foreign keys, for the reason ``Notification`` states, plus one specific
    to this table: a mark must never be able to confirm or deny that a given
    ``notification_id`` exists. Ids are sequential, so a FK violation would
    turn this table into an existence oracle for other users' notifications --
    ``notifications_mark_read`` checks each id against the audience predicate
    before inserting instead.
    """

    __tablename__ = "notification_read"

    auth_user_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=False)
    notification_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=False)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # NULL = present in the inbox. Set = this viewer deleted it; every read
    # funnels through ``NotificationRepository.audience_clause``, which drops
    # the row for this identity alone.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationDelivery(db.Base):
    """One row per message actually handed to an outside channel.

    The ledger that makes delivery idempotent: the consumer inserts
    ``ON CONFLICT DO NOTHING`` on ``(channel, target, dedupe_key)`` in the same
    transaction as the outbox command to the bot, so a redelivered event finds
    its row and sends nothing. Skips (preference off, no Discord linked) are
    not recorded -- only sends.

    No foreign keys, like ``Notification``: a journal outlives its referents.
    ``ponytail:`` no retention; add it to the purge tick when the table gets big.
    """

    __tablename__ = "notification_delivery"
    __table_args__ = (UniqueConstraint("channel", "target", "dedupe_key", name="uq_notification_delivery_target"),)

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    # ``discord_dm`` | ``discord_channel``.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # The Discord user id (DM) or channel id, as text: snowflakes, not keys.
    target: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    notification_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NotificationPreference(db.Base):
    """A user's opt-outs from Discord DMs, per kind group.

    ``discord_dm`` holds only what the user changed: ``{"matches": false}``.
    A missing key is the default (on), so a new group needs no backfill.
    """

    __tablename__ = "notification_preference"

    auth_user_id: Mapped[int] = mapped_column(
        BigInteger(),
        ForeignKey("auth.user.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    # NOTE: JSONB does not track in-place mutation -- always reassign.
    discord_dm: Mapped[dict[str, bool]] = mapped_column(JSONB(), nullable=False, server_default=text("'{}'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NotificationWorkspaceConfig(db.Base):
    """Where a workspace's broadcast notifications are posted, and which ones.

    Its own table rather than columns on ``workspace`` (same call as
    ``balancer.workspace_config``): only the admin settings screen reads it,
    and it must never reach the public ``WorkspaceRead``.
    """

    __tablename__ = "notification_workspace_config"

    workspace_id: Mapped[int] = mapped_column(
        BigInteger(),
        ForeignKey("workspace.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    # NULL = no channel picked yet: broadcasts are skipped.
    discord_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    locale: Mapped[str] = mapped_column(String(2), nullable=False, server_default=text("'ru'"))
    # NOTE: JSONB does not track in-place mutation -- always reassign.
    broadcast_kinds: Mapped[list[str]] = mapped_column(
        JSONB(),
        nullable=False,
        server_default=text("""'["registration.opened", "check_in.opened"]'"""),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
