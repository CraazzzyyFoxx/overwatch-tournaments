"""Room-chat storage. Three tables, one room key.

Only ``ChatMessage`` extends ``BaseRepository``: the settings and mute tables
are keyed by the room pair (plus the muted account) and have no ``id`` column,
which is exactly what ``BaseRepository.get``/``count``/``list`` are written
against. Inheriting them would hand callers four methods that raise
``AttributeError`` on the first use.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

__all__ = ("ChatMessageRepository", "ChatMuteRepository", "ChatRoomSettingsRepository")


class ChatMessageRepository(BaseRepository[models.ChatMessage]):
    def __init__(self) -> None:
        super().__init__(models.ChatMessage)

    async def history(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        after_id: int | None = None,
        limit: int,
    ) -> Sequence[models.ChatMessage]:
        """Messages of one room, oldest-first, deleted ones omitted.

        Two modes on one index. ``after_id=None`` is the panel opening: the
        NEWEST ``limit`` messages, which has to be selected descending and
        reversed. ``after_id`` is the catch-up after a reconnect: everything
        that arrived since, ascending, still capped so a client that was away
        for an hour cannot ask for the whole room in one response.
        """
        model = self.model
        room = (model.room_kind == room_kind, model.room_ref_id == room_ref_id, model.deleted_at.is_(None))

        if after_id is not None:
            rows = await session.scalars(
                self.select().where(*room, model.id > after_id).order_by(model.id.asc()).limit(limit)
            )
            return rows.all()

        rows = await session.scalars(self.select().where(*room).order_by(model.id.desc()).limit(limit))
        return list(reversed(rows.all()))

    async def throttle_exceeded(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        auth_user_id: int,
        limit: int,
        window: timedelta,
    ) -> bool:
        """Has this author already sent ``limit`` messages in the last ``window``?

        One query: filter the author's messages in this room down to the window,
        then ask whether a ``limit``-th one exists. The comparison is
        ``func.now()``, never a Python clock -- a worker whose time drifts must
        not get its own private rate limit. Deleted messages still count: they
        cost the same to send, and letting a spammer reset the window by
        deleting would be a new way to spam.
        """
        model = self.model
        found = await session.scalar(
            sa.select(model.id)
            .where(
                model.room_kind == room_kind,
                model.room_ref_id == room_ref_id,
                model.auth_user_id == auth_user_id,
                model.created_at > sa.func.now() - window,
            )
            .order_by(model.id.desc())
            .offset(limit - 1)
            .limit(1)
        )
        return found is not None

    async def get_in_room(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        message_id: int,
    ) -> models.ChatMessage | None:
        """A single live message, scoped to its room.

        The room is part of the lookup, not checked afterwards: ids are global,
        so a moderator of room A must never be able to delete a message of
        room B by passing its id.
        """
        model = self.model
        return await session.scalar(
            self.select().where(
                model.id == message_id,
                model.room_kind == room_kind,
                model.room_ref_id == room_ref_id,
                model.deleted_at.is_(None),
            )
        )

    async def soft_delete(
        self,
        session: AsyncSession,
        message: models.ChatMessage,
        *,
        by_auth_user_id: int,
        now: datetime,
    ) -> models.ChatMessage:
        message.deleted_at = now
        message.deleted_by_auth_user_id = by_auth_user_id
        await session.flush()
        return message

    async def purge_older_than(self, session: AsyncSession, cutoff: datetime) -> int:
        result = await session.execute(sa.delete(self.model).where(self.model.created_at < cutoff))
        return result.rowcount or 0


class ChatRoomSettingsRepository:
    async def get(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
    ) -> models.ChatRoomSettings | None:
        """The room's overrides, or ``None`` when it still runs on its defaults."""
        return await session.scalar(
            sa.select(models.ChatRoomSettings).where(
                models.ChatRoomSettings.room_kind == room_kind,
                models.ChatRoomSettings.room_ref_id == room_ref_id,
            )
        )

    async def set_spectators_can_read(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        value: bool,
        by_auth_user_id: int,
    ) -> models.ChatRoomSettings:
        """Upsert the toggle. First write for a room materializes its row."""
        stmt = (
            pg_insert(models.ChatRoomSettings)
            .values(
                room_kind=room_kind,
                room_ref_id=room_ref_id,
                spectators_can_read=value,
                updated_by_auth_user_id=by_auth_user_id,
            )
            .on_conflict_do_update(
                index_elements=[models.ChatRoomSettings.room_kind, models.ChatRoomSettings.room_ref_id],
                set_={
                    "spectators_can_read": value,
                    "updated_by_auth_user_id": by_auth_user_id,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(models.ChatRoomSettings)
            # Without populate_existing the ORM hands back the copy already in
            # the identity map and the RETURNING values are discarded — so a
            # second toggle in one session reports the value it replaced.
            .execution_options(populate_existing=True)
        )
        row = await session.scalar(stmt)
        assert row is not None  # an upsert with RETURNING always yields a row
        return row


class ChatMuteRepository:
    def _live(self, room_kind: str, room_ref_id: int) -> tuple[sa.ColumnElement[bool], ...]:
        """Mutes of this room that are still in force.

        Expiry is a read-time predicate and never a sweeper: an elapsed row is
        inert, so a missed job or a skewed clock can only fail OPEN on schedule
        -- it can never keep somebody muted past their time.
        """
        model = models.ChatMute
        return (
            model.room_kind == room_kind,
            model.room_ref_id == room_ref_id,
            sa.or_(model.muted_until.is_(None), model.muted_until > sa.func.now()),
        )

    async def active_for(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        auth_user_id: int,
    ) -> models.ChatMute | None:
        return await session.scalar(
            sa.select(models.ChatMute).where(
                *self._live(room_kind, room_ref_id),
                models.ChatMute.auth_user_id == auth_user_id,
            )
        )

    async def list_active(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
    ) -> Sequence[models.ChatMute]:
        rows = await session.scalars(
            sa.select(models.ChatMute)
            .where(*self._live(room_kind, room_ref_id))
            .order_by(models.ChatMute.created_at.desc())
        )
        return rows.all()

    async def set(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        auth_user_id: int,
        muted_until: datetime | None,
        reason: str | None,
        by_auth_user_id: int,
    ) -> models.ChatMute:
        """Upsert. Re-muting an already-muted account replaces the term."""
        stmt = (
            pg_insert(models.ChatMute)
            .values(
                room_kind=room_kind,
                room_ref_id=room_ref_id,
                auth_user_id=auth_user_id,
                muted_until=muted_until,
                reason=reason,
                created_by_auth_user_id=by_auth_user_id,
            )
            .on_conflict_do_update(
                index_elements=[
                    models.ChatMute.room_kind,
                    models.ChatMute.room_ref_id,
                    models.ChatMute.auth_user_id,
                ],
                set_={
                    "muted_until": muted_until,
                    "reason": reason,
                    "created_by_auth_user_id": by_auth_user_id,
                    "created_at": sa.func.now(),
                },
            )
            .returning(models.ChatMute)
            # See ChatRoomSettingsRepository.set_spectators_can_read: an
            # identity-mapped row would shadow the RETURNING values, and
            # re-muting an already-muted account is exactly that case.
            .execution_options(populate_existing=True)
        )
        row = await session.scalar(stmt)
        assert row is not None  # an upsert with RETURNING always yields a row
        return row

    async def clear(
        self,
        session: AsyncSession,
        *,
        room_kind: str,
        room_ref_id: int,
        auth_user_id: int,
    ) -> bool:
        result = await session.execute(
            sa.delete(models.ChatMute).where(
                models.ChatMute.room_kind == room_kind,
                models.ChatMute.room_ref_id == room_ref_id,
                models.ChatMute.auth_user_id == auth_user_id,
            )
        )
        return (result.rowcount or 0) > 0

    async def purge_expired_before(self, session: AsyncSession, cutoff: datetime) -> int:
        result = await session.execute(
            sa.delete(models.ChatMute).where(
                models.ChatMute.muted_until.is_not(None),
                models.ChatMute.muted_until < cutoff,
            )
        )
        return result.rowcount or 0
