from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("DISCORD_MESSAGE_STATUSES", "DiscordMessage")

#: ``pending`` -- queued for the bot; ``posted`` -- exists in Discord;
#: ``failed`` -- Discord refused it (``error`` says why); ``deleting`` -- a
#: delete is queued; ``deleted`` -- gone from Discord (or found already gone).
DISCORD_MESSAGE_STATUSES = ("pending", "posted", "failed", "deleting", "deleted")


class DiscordMessage(db.Base):
    """One row per message the platform asked the bot to send.

    The single state of everything the bot says *on the platform's behalf* --
    notification DMs, workspace broadcasts, mix signup and lineup posts. What
    the bot answers inside Discord itself (ephemeral button replies, match-log
    feedback) is not recorded: nobody outside Discord ever addresses it again.

    The publisher inserts the row in its own transaction and names it in the
    command (``DiscordCommandEvent.message_ref``); discord-service fills in
    ``discord_channel_id`` / ``message_id`` / ``status`` once Discord answers.
    Every later edit or delete names the row, never a Discord id, so a
    publisher never has to learn snowflakes and a delete works the same for a
    DM and a channel post.

    ``subject`` is the platform object the message is about (``mix:42``,
    ``notification:7``, ``broadcast:<kind>:<key>``) and ``slot`` its role there
    (``signup``, ``lineup:0:3``, ``dm``, ``channel``): "every Discord message of
    this mix" is one indexed lookup.

    ``(channel, target, dedupe_key)`` is the idempotency claim notification
    delivery relies on: inserting ``ON CONFLICT DO NOTHING`` in the same
    transaction as the outbox command makes a redelivered event send nothing.
    A message with no ``dedupe_key`` (a host pressing "post" twice means two
    posts) never conflicts -- NULLs are distinct.

    No foreign keys, like the rest of the platform journals: the row outlives
    its subject, which is exactly when a delete still has to find the message.
    ``ponytail:`` no retention; add it to the purge tick when the table gets big.
    """

    __tablename__ = "discord_message"
    __table_args__ = (
        UniqueConstraint("channel", "target", "dedupe_key", name="uq_discord_message_target"),
        CheckConstraint(
            "status IN ('pending', 'posted', 'failed', 'deleting', 'deleted')",
            name="ck_discord_message_status",
        ),
        Index("ix_discord_message_subject", "subject"),
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    # ``discord_dm`` | ``discord_channel``.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # Where it was addressed: the Discord user id (DM) or channel id, as text.
    target: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Wide enough for ``broadcast:<dedupe_key>``, which the ledger rows this
    # table took over carry as their subject.
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    slot: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    notification_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    # Where it actually lives once posted -- for a DM, the DM channel, which is
    # what an edit or a delete needs and is not ``target``.
    discord_channel_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
