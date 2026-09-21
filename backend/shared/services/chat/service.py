"""The room chat itself: read, write, moderate.

Everything here is room-kind agnostic. The one thing that is not — who the
caller is in this room — arrives as a ``ChatAccess`` resolver supplied by the
service that owns the domain.

Design: docs/plans/2026-09-21-shared-room-chat.md.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.platform.chat import ChatMessage
from shared.repository.chat import (
    ChatMessageRepository,
    ChatMuteRepository,
    ChatRoomSettingsRepository,
)
from shared.repository.identity import AuthUserRepository
from shared.services.chat.access import ChatAccess, ChatMembership
from shared.services.chat.room import CHAT_DOMAIN, ChatRoom
from shared.services.chat.schemas import (
    HISTORY_DEFAULT,
    HISTORY_MAX,
    MAX_BODY_LENGTH,
    MAX_RAW_BODY_LENGTH,
    ChatEnvelope,
    ChatMessageRead,
    ChatMuteRead,
    ChatSettings,
    ChatViewer,
)
from shared.services.realtime import DomainEvent, emit

__all__ = ("EVENT_DELETED", "EVENT_MESSAGE", "EVENT_MUTED", "EVENT_UNMUTED", "EVENT_VISIBILITY", "ChatService")

EVENT_MESSAGE = "chat.message"
EVENT_DELETED = "chat.message_deleted"
EVENT_MUTED = "chat.muted"
EVENT_UNMUTED = "chat.unmuted"
#: The gateway watches for THIS event type and re-authorizes everyone currently
#: subscribed to the topic (gateway/internal/ws/revoke.go). Renaming it here
#: without renaming it there turns the toggle back into an advisory one.
EVENT_VISIBILITY = "chat.visibility_changed"

THROTTLE_WINDOW = timedelta(seconds=10)
THROTTLE_MESSAGES = 10

# Every C0/C1 control except the newline a multi-line message legitimately
# carries (tab included: it only ever arrives by paste and buys nothing here).
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _sanitize(body: str) -> str:
    if len(body) > MAX_RAW_BODY_LENGTH:
        # Refused before sanitizing: trimming a megabyte of control characters
        # down to something acceptable would reward the sender for sending it.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"message must be at most {MAX_RAW_BODY_LENGTH} characters",
        )
    cleaned = _BLANK_LINES_RE.sub("\n\n", _CONTROL_RE.sub("", body)).strip()
    if not cleaned or len(cleaned) > MAX_BODY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"message must be 1..{MAX_BODY_LENGTH} characters",
        )
    return cleaned


def _read(row: ChatMessage, avatar_url: str | None = None) -> ChatMessageRead:
    return ChatMessageRead(
        id=row.id,
        created_at=row.created_at,
        auth_user_id=row.auth_user_id,
        author_name=row.author_name,
        author_role=row.author_role,
        body=row.body,
        author_avatar_url=avatar_url,
    )


class ChatService:
    def __init__(
        self,
        access: ChatAccess,
        *,
        messages: ChatMessageRepository | None = None,
        settings: ChatRoomSettingsRepository | None = None,
        mutes: ChatMuteRepository | None = None,
        auth_users: AuthUserRepository | None = None,
    ) -> None:
        self.access = access
        self.messages = messages or ChatMessageRepository()
        self.settings = settings or ChatRoomSettingsRepository()
        self.mutes = mutes or ChatMuteRepository()
        self.auth_users = auth_users or AuthUserRepository()

    # ── policy ───────────────────────────────────────────────────────────────

    async def spectators_can_read(self, session: AsyncSession, room: ChatRoom) -> bool:
        row = await self.settings.get(session, room_kind=room.kind, room_ref_id=room.ref_id)
        return room.spectators_can_read_default if row is None else row.spectators_can_read

    async def _reader(
        self,
        session: AsyncSession,
        auth_user: Any | None,
        room: ChatRoom,
    ) -> tuple[ChatMembership, bool]:
        """Membership + the room's spectator setting, or 403.

        The resolver already refused anyone who may not see the ROOM; this adds
        the only rule the resolver deliberately does not know — whether merely
        watching includes reading the chat.
        """
        membership = await self.access.resolve(session, auth_user, room)
        visible = await self.spectators_can_read(session, room)
        if membership.is_spectator and not visible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This room's chat is not open to spectators",
            )
        return membership, visible

    async def _moderator(self, session: AsyncSession, auth_user: Any | None, room: ChatRoom) -> ChatMembership:
        membership, _ = await self._reader(session, auth_user, room)
        if not membership.can_moderate:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot moderate this room's chat",
            )
        return membership

    async def _emit(
        self,
        session: AsyncSession,
        room: ChatRoom,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor_user_id: int | None,
    ) -> None:
        """Non-durable, always.

        The table is the history now. A durable row would store every message
        twice and put the realtime replay cursor and the chat's own ``after_id``
        pagination in charge of the same thing; a reconnecting client catches up
        with ``GET ?after_id=`` instead, which also repairs a gap left by a
        dropped publish that no reconnect would have revealed.
        """
        await emit(
            session,
            scope=room.scope,
            data=DomainEvent(
                domain=CHAT_DOMAIN,
                event_type=event_type,
                payload=payload,
                durable=False,
            ),
            actor_user_id=actor_user_id,
        )

    # ── reads ────────────────────────────────────────────────────────────────

    async def envelope(
        self,
        session: AsyncSession,
        auth_user: Any | None,
        room: ChatRoom,
        *,
        after_id: int | None = None,
        limit: int = HISTORY_DEFAULT,
    ) -> ChatEnvelope:
        membership, visible = await self._reader(session, auth_user, room)
        rows = await self.messages.history(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            after_id=after_id,
            limit=max(1, min(int(limit), HISTORY_MAX)),
        )
        # One extra two-column query for the whole page, not one per row: the
        # transcript usually repeats a handful of authors.
        avatars = await self.auth_users.avatar_urls(session, {row.auth_user_id for row in rows})

        mute = None
        if auth_user is not None:
            mute = await self.mutes.active_for(
                session,
                room_kind=room.kind,
                room_ref_id=room.ref_id,
                auth_user_id=auth_user.id,
            )
        mutes = (
            [
                ChatMuteRead(
                    auth_user_id=row.auth_user_id,
                    muted_until=row.muted_until,
                    reason=row.reason,
                    created_by_auth_user_id=row.created_by_auth_user_id,
                    created_at=row.created_at,
                )
                for row in await self.mutes.list_active(session, room_kind=room.kind, room_ref_id=room.ref_id)
            ]
            if membership.can_moderate
            else []
        )

        return ChatEnvelope(
            messages=[_read(row, avatars.get(row.auth_user_id)) for row in rows],
            settings=ChatSettings(spectators_can_read=visible),
            viewer=ChatViewer(
                role=membership.role,
                can_write=membership.can_write and mute is None,
                can_moderate=membership.can_moderate,
                muted_until=mute.muted_until if mute is not None else None,
            ),
            mutes=mutes,
        )

    # ── writes ───────────────────────────────────────────────────────────────

    async def post(
        self,
        session: AsyncSession,
        auth_user: Any,
        room: ChatRoom,
        body: str,
    ) -> ChatMessageRead:
        membership, _ = await self._reader(session, auth_user, room)
        if not membership.can_write:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot write in this room's chat",
            )

        mute = await self.mutes.active_for(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            auth_user_id=auth_user.id,
        )
        if mute is not None:
            # A coded error, not a bare 403: the client tells the difference
            # between "you were never allowed here" and "you are muted until X".
            raise ApiHTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=[
                    ApiExc(
                        code="chat_muted",
                        msg=(
                            "You are muted in this room"
                            if mute.muted_until is None
                            else f"You are muted in this room until {mute.muted_until.isoformat()}"
                        ),
                    )
                ],
            )

        clean = _sanitize(body)
        if await self.messages.throttle_exceeded(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            auth_user_id=auth_user.id,
            limit=THROTTLE_MESSAGES,
            window=THROTTLE_WINDOW,
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many messages, slow down",
            )

        row = await self.messages.create(
            session,
            ChatMessage(
                room_kind=room.kind,
                room_ref_id=room.ref_id,
                auth_user_id=auth_user.id,
                author_name=membership.display_name,
                author_role=membership.role,
                body=clean,
            ),
        )
        # ``created_at`` is a server default, so the flushed row does not carry
        # it yet — and an async lazy refresh on attribute access raises
        # MissingGreenlet rather than filling it in.
        await session.refresh(row, ["created_at"])

        # Also on the event, not just the reply: every other subscriber renders
        # this message straight from the payload and would otherwise show a
        # faceless row until the next full read.
        avatars = await self.auth_users.avatar_urls(session, (auth_user.id,))
        message = _read(row, avatars.get(auth_user.id))
        await self._emit(
            session,
            room,
            EVENT_MESSAGE,
            message.model_dump(mode="json"),
            actor_user_id=auth_user.id,
        )
        await session.commit()
        return message

    async def delete(
        self,
        session: AsyncSession,
        auth_user: Any,
        room: ChatRoom,
        message_id: int,
    ) -> None:
        membership, _ = await self._reader(session, auth_user, room)
        row = await self.messages.get_in_room(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            message_id=message_id,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        if not membership.can_moderate and row.auth_user_id != auth_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own messages",
            )

        await self.messages.soft_delete(session, row, by_auth_user_id=auth_user.id, now=datetime.now(UTC))
        await self._emit(session, room, EVENT_DELETED, {"id": row.id}, actor_user_id=auth_user.id)
        await session.commit()

    async def set_settings(
        self,
        session: AsyncSession,
        auth_user: Any,
        room: ChatRoom,
        *,
        spectators_can_read: bool,
    ) -> ChatSettings:
        await self._moderator(session, auth_user, room)
        if await self.spectators_can_read(session, room) == spectators_can_read:
            # No event on a no-op: the gateway re-authorizes every subscriber of
            # the topic on this event, and a toggle that did not move must not
            # cost that.
            return ChatSettings(spectators_can_read=spectators_can_read)

        await self.settings.set_spectators_can_read(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            value=spectators_can_read,
            by_auth_user_id=auth_user.id,
        )
        await self._emit(
            session,
            room,
            EVENT_VISIBILITY,
            {"spectators_can_read": spectators_can_read},
            actor_user_id=auth_user.id,
        )
        await session.commit()
        return ChatSettings(spectators_can_read=spectators_can_read)

    async def set_mute(
        self,
        session: AsyncSession,
        auth_user: Any,
        room: ChatRoom,
        target_auth_user_id: int,
        *,
        minutes: int | None,
        reason: str | None,
    ) -> ChatMuteRead:
        await self._moderator(session, auth_user, room)
        if target_auth_user_id == auth_user.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="You cannot mute yourself",
            )

        muted_until = None if minutes is None else datetime.now(UTC) + timedelta(minutes=minutes)
        row = await self.mutes.set(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            auth_user_id=target_auth_user_id,
            muted_until=muted_until,
            reason=reason,
            by_auth_user_id=auth_user.id,
        )
        mute = ChatMuteRead(
            auth_user_id=target_auth_user_id,
            muted_until=muted_until,
            reason=reason,
            created_by_auth_user_id=auth_user.id,
            created_at=row.created_at if row.created_at is not None else datetime.now(UTC),
        )
        await self._emit(session, room, EVENT_MUTED, mute.model_dump(mode="json"), actor_user_id=auth_user.id)
        await session.commit()
        return mute

    async def clear_mute(
        self,
        session: AsyncSession,
        auth_user: Any,
        room: ChatRoom,
        target_auth_user_id: int,
    ) -> bool:
        await self._moderator(session, auth_user, room)
        cleared = await self.mutes.clear(
            session,
            room_kind=room.kind,
            room_ref_id=room.ref_id,
            auth_user_id=target_auth_user_id,
        )
        if cleared:
            await self._emit(
                session,
                room,
                EVENT_UNMUTED,
                {"auth_user_id": target_auth_user_id},
                actor_user_id=auth_user.id,
            )
            await session.commit()
        return cleared
