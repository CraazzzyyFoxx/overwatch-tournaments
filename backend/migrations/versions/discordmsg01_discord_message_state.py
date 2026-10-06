"""One state for every Discord message the platform sends: ``discord_message``.

Revision ID: discordmsg01
Revises: objmap01
Create Date: 2026-10-06 00:00:00.000000

``notification_delivery`` -- the idempotency ledger of notification DMs and
broadcasts -- becomes ``discord_message``, the record of *every* message the
bot sends on the platform's behalf: notifications, broadcasts, mix signup and
lineup posts. A row now also carries what Discord answered (``status``, the
message's ``discord_channel_id`` / ``message_id``, ``error``) and what it is
about (``subject`` / ``slot``), so a message can be edited and deleted later by
its row alone.

Renamed in place rather than copied: the ledger's unique claim
``(channel, target, dedupe_key)`` keeps guarding redelivered notification
events across the deploy. Existing rows were all handed to the bot, so they
become ``posted`` with no Discord ids (those were never recorded) -- visible in
the admin inspector as before, not deletable. ``dedupe_key`` turns nullable: a
host's post has nothing to deduplicate on.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "discordmsg01"
down_revision: str | Sequence[str] | None = "objmap01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("notification_delivery", "discord_message")
    op.execute("ALTER SEQUENCE notification_delivery_id_seq RENAME TO discord_message_id_seq")
    op.execute("ALTER INDEX notification_delivery_pkey RENAME TO discord_message_pkey")
    op.execute(
        "ALTER TABLE discord_message RENAME CONSTRAINT uq_notification_delivery_target TO uq_discord_message_target"
    )
    op.alter_column("discord_message", "dedupe_key", existing_type=sa.String(length=128), nullable=True)

    op.add_column("discord_message", sa.Column("subject", sa.String(length=160), nullable=True))
    op.add_column("discord_message", sa.Column("slot", sa.String(length=64), nullable=True))
    op.add_column("discord_message", sa.Column("status", sa.String(length=16), nullable=False, server_default="posted"))
    op.add_column("discord_message", sa.Column("discord_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("discord_message", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.add_column("discord_message", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("discord_message", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # The subjects notification delivery writes from now on, so an old row and
    # a new one about the same notification read alike.
    op.execute(
        """
        UPDATE discord_message SET
            subject = CASE
                WHEN notification_id IS NOT NULL THEN 'notification:' || notification_id
                ELSE 'broadcast:' || dedupe_key
            END,
            slot = CASE channel WHEN 'discord_dm' THEN 'dm' ELSE 'channel' END
        """
    )
    op.alter_column("discord_message", "subject", existing_type=sa.String(length=160), nullable=False)
    op.alter_column("discord_message", "slot", existing_type=sa.String(length=64), nullable=False)
    # Backfilled rows were sent; a row written from now on starts waiting.
    op.alter_column("discord_message", "status", existing_type=sa.String(length=16), server_default="pending")
    op.create_check_constraint(
        "ck_discord_message_status",
        "discord_message",
        "status IN ('pending', 'posted', 'failed', 'deleting', 'deleted')",
    )
    op.create_index("ix_discord_message_subject", "discord_message", ["subject"])


def downgrade() -> None:
    # Posts with nothing to deduplicate on have no place in the old ledger.
    op.execute("DELETE FROM discord_message WHERE dedupe_key IS NULL")
    op.drop_index("ix_discord_message_subject", table_name="discord_message")
    op.drop_constraint("ck_discord_message_status", "discord_message", type_="check")
    for column in ("updated_at", "error", "message_id", "discord_channel_id", "status", "slot", "subject"):
        op.drop_column("discord_message", column)
    op.alter_column("discord_message", "dedupe_key", existing_type=sa.String(length=128), nullable=False)
    op.execute(
        "ALTER TABLE discord_message RENAME CONSTRAINT uq_discord_message_target TO uq_notification_delivery_target"
    )
    op.execute("ALTER INDEX discord_message_pkey RENAME TO notification_delivery_pkey")
    op.execute("ALTER SEQUENCE discord_message_id_seq RENAME TO notification_delivery_id_seq")
    op.rename_table("discord_message", "notification_delivery")
