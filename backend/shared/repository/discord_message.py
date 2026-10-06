"""The single state of what the bot said on the platform's behalf (``discord_message``).

Publishers ``claim`` a row in the transaction that decides to send; the bot,
the only process that hears Discord answer, moves it through ``mark_*``.
Everybody else reads by ``subject`` -- "every Discord message of mix 42" -- and
never by a Discord id.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

__all__ = ("DiscordMessageRepository",)

#: Rows that still stand for a message in Discord (or one about to be).
LIVE_STATUSES = ("pending", "posted")


class DiscordMessageRepository(BaseRepository[models.DiscordMessage]):
    def __init__(self) -> None:
        super().__init__(models.DiscordMessage)

    async def claim(
        self,
        session: AsyncSession,
        *,
        channel: str,
        target: str,
        subject: str,
        slot: str,
        kind: str,
        card_json: dict | None = None,
        dedupe_key: str | None = None,
        notification_id: int | None = None,
        workspace_id: int | None = None,
    ) -> int | None:
        """Record a message about to be sent; its id, or ``None`` when it already was.

        Asking "am I the one who gets to send this?" and answering it in one
        statement is the point -- a SELECT-then-INSERT would let a redelivered
        event slip between the two. Without a ``dedupe_key`` there is nothing to
        conflict on and every call is a new message.
        """
        statement = (
            pg_insert(models.DiscordMessage.__table__)
            .values(
                channel=channel,
                target=target,
                subject=subject,
                slot=slot,
                kind=kind,
                card_json=card_json,
                dedupe_key=dedupe_key,
                notification_id=notification_id,
                workspace_id=workspace_id,
                status="pending",
            )
            # Named by columns rather than by the constraint: the same clause
            # then compiles on SQLite, which the delivery tests run on.
            .on_conflict_do_nothing(index_elements=["channel", "target", "dedupe_key"])
            .returning(models.DiscordMessage.__table__.c.id)
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    async def for_subject(
        self,
        session: AsyncSession,
        subject: str,
        *,
        slot: str | None = None,
        statuses: Sequence[str] | None = None,
    ) -> list[models.DiscordMessage]:
        """Messages about one platform object, oldest first."""
        query = self.select().where(self.model.subject == subject)
        if slot is not None:
            query = query.where(self.model.slot == slot)
        if statuses is not None:
            query = query.where(self.model.status.in_(tuple(statuses)))
        result = await session.execute(query.order_by(self.model.id))
        return list(result.scalars().all())

    async def live_for_workspace(
        self, session: AsyncSession, workspace_id: int, *, subject_prefix: str, slot: str
    ) -> list[models.DiscordMessage]:
        """A workspace's live messages in one slot of one subject kind (``mix:``), oldest first."""
        result = await session.execute(
            self.select()
            .where(
                self.model.workspace_id == workspace_id,
                self.model.subject.startswith(subject_prefix, autoescape=True),
                self.model.slot == slot,
                self.model.status.in_(LIVE_STATUSES),
            )
            .order_by(self.model.id)
        )
        return list(result.scalars().all())

    async def get_for_update(self, session: AsyncSession, row_id: int) -> models.DiscordMessage | None:
        """Row-locked, freshly read: serializes everyone re-rendering this message.

        ``populate_existing``: a row already in the session's identity map would
        otherwise come back with the state it was first loaded with.
        """
        return await session.scalar(
            self.select().where(self.model.id == row_id).with_for_update().execution_options(populate_existing=True)
        )

    async def recent_for_targets(
        self,
        session: AsyncSession,
        *,
        channel: str,
        targets: Sequence[str],
        limit: int,
    ) -> list[models.DiscordMessage]:
        """The newest sends on one channel to any of these targets, newest first.

        ``targets`` empty means the account has nothing connected on that
        channel, which is an empty answer rather than an unfiltered one: an
        ``IN ()`` that degraded into "every delivery on the platform" would put
        strangers' sends in an operator's account inspector.
        """
        if not targets:
            return []
        result = await session.execute(
            self.select()
            .where(self.model.channel == channel, self.model.target.in_(tuple(targets)))
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(limit),
        )
        return list(result.scalars().all())

    async def _set(self, session: AsyncSession, message_id: int, **values: object) -> None:
        await session.execute(
            sa.update(self.model).where(self.model.id == message_id).values(**values, updated_at=datetime.now(UTC))
        )

    async def set_card(self, session: AsyncSession, row_id: int, card_json: dict) -> None:
        await self._set(session, row_id, card_json=card_json)

    async def mark_posted(
        self, session: AsyncSession, row_id: int, *, discord_channel_id: int, discord_message_id: int
    ) -> bool:
        """Record where a sent message landed; ``False`` when the row was no longer ``pending``.

        Conditional on purpose: a delete can reach the row while the bot is
        still inside ``channel.send``, moving it to ``deleting``. Overwriting
        that with ``posted`` would strand a message everyone believes is gone,
        so the update simply does not apply and the caller -- the only process
        holding the message -- deletes what it just sent.
        """
        result = await session.execute(
            sa.update(self.model)
            .where(self.model.id == row_id, self.model.status == "pending")
            .values(
                status="posted",
                discord_channel_id=discord_channel_id,
                message_id=discord_message_id,
                error=None,
                updated_at=datetime.now(UTC),
            )
        )
        return result.rowcount > 0

    async def mark_failed(self, session: AsyncSession, row_id: int, *, error: str) -> None:
        await self._set(session, row_id, status="failed", error=error[:500])

    async def mark_deleting(self, session: AsyncSession, row_id: int) -> None:
        await self._set(session, row_id, status="deleting")

    async def mark_deleted(self, session: AsyncSession, row_id: int) -> None:
        await self._set(session, row_id, status="deleted")
