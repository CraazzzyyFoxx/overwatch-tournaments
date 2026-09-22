"""Event notifications: dedupe key, delivery ledger, DM preferences, workspace config.

Revision ID: notif004
Revises: encgame01
Create Date: 2026-09-23 00:00:00.000000

Four pieces of docs/superpowers/specs/2026-09-22-event-notifications-design.md §5:

* ``notification.dedupe_key`` + a NON-unique partial index. ``notify()`` checks
  for an existing row with the same kind/key/recipient before writing; a unique
  index would turn two racing status transitions into an ``IntegrityError``
  inside ``transition_status`` instead of a rare duplicate row.
* ``notification_delivery`` -- the idempotency ledger of messages handed to
  Discord, unique on ``(channel, target, dedupe_key)``. No FKs: a journal.
* ``notification_preference`` -- per-user DM opt-outs by kind group; a missing
  key means the default (on).
* ``notification_workspace_config`` -- the workspace's broadcast channel,
  locale and enabled kinds. Its own table so it never leaks into the public
  workspace read.

Pure expand: nothing reads the new columns until the producers ship.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "notif004"
down_revision: str | Sequence[str] | None = "encgame01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification", sa.Column("dedupe_key", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_notification_dedupe",
        "notification",
        ["kind", "dedupe_key"],
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )

    op.create_table(
        "notification_delivery",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("notification_id", sa.BigInteger(), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "target", "dedupe_key", name="uq_notification_delivery_target"),
    )

    op.create_table(
        "notification_preference",
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "discord_dm",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("auth_user_id"),
    )

    op.create_table(
        "notification_workspace_config",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("locale", sa.String(length=2), server_default=sa.text("'ru'"), nullable=False),
        sa.Column(
            "broadcast_kinds",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("""'["registration.opened", "check_in.opened"]'"""),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_workspace_config")
    op.drop_table("notification_preference")
    op.drop_table("notification_delivery")
    op.drop_index("ix_notification_dedupe", table_name="notification")
    op.drop_column("notification", "dedupe_key")
