"""Room-chat policy: who reads, who writes, who is silenced.

The service's own IO is three repositories and one ``emit``; all four are
substituted here, because what is worth pinning is the POLICY between them --
every rule below was a deliberate decision in
``docs/plans/2026-09-21-shared-room-chat.md`` and would be invisible in a
database test.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.services.chat import (  # noqa: E402
    EVENT_DELETED,
    EVENT_MESSAGE,
    EVENT_MUTED,
    EVENT_VISIBILITY,
    ChatMembership,
    ChatRoom,
    ChatService,
)

CAPTAIN = SimpleNamespace(id=7)
STAFF = SimpleNamespace(id=1)
VIEWER = SimpleNamespace(id=99)


class _Session:
    """Only what the service touches: a commit, and a no-op column refresh."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, instance: Any, _columns: Any = None) -> None:
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(UTC)


class _Messages:
    def __init__(self, rows: list[Any] | None = None, *, throttled: bool = False) -> None:
        self.rows = rows or []
        self.throttled = throttled
        self.deleted: list[tuple[int, int]] = []
        self._next_id = 100

    async def history(self, _session: Any, **_kw: Any) -> list[Any]:
        return list(self.rows)

    async def throttle_exceeded(self, _session: Any, **_kw: Any) -> bool:
        return self.throttled

    async def get_in_room(self, _session: Any, *, message_id: int, **_kw: Any) -> Any:
        return next((row for row in self.rows if row.id == message_id), None)

    async def soft_delete(self, _session: Any, message: Any, *, by_auth_user_id: int, now: datetime) -> Any:
        message.deleted_at = now
        self.deleted.append((message.id, by_auth_user_id))
        return message

    async def create(self, _session: Any, instance: Any) -> Any:
        instance.id = self._next_id
        self._next_id += 1
        self.rows.append(instance)
        return instance


class _Settings:
    def __init__(self, value: bool | None = None) -> None:
        self.value = value
        self.writes: list[bool] = []

    async def get(self, _session: Any, **_kw: Any) -> Any:
        return None if self.value is None else SimpleNamespace(spectators_can_read=self.value)

    async def set_spectators_can_read(self, _session: Any, *, value: bool, **_kw: Any) -> Any:
        self.value = value
        self.writes.append(value)
        return SimpleNamespace(spectators_can_read=value)


class _Mutes:
    def __init__(self, active: Any = None) -> None:
        self.active = active
        self.set_calls: list[dict[str, Any]] = []
        self.cleared: list[int] = []

    async def active_for(self, _session: Any, *, auth_user_id: int, **_kw: Any) -> Any:
        return self.active if self.active is not None and self.active.auth_user_id == auth_user_id else None

    async def list_active(self, _session: Any, **_kw: Any) -> list[Any]:
        return [self.active] if self.active is not None else []

    async def set(self, _session: Any, **kw: Any) -> Any:
        self.set_calls.append(kw)
        return SimpleNamespace(created_at=datetime.now(UTC))

    async def clear(self, _session: Any, *, auth_user_id: int, **_kw: Any) -> bool:
        self.cleared.append(auth_user_id)
        return True


class _Access:
    def __init__(self, membership: ChatMembership | None) -> None:
        self.membership = membership

    async def resolve(self, _session: Any, _auth_user: Any, _room: ChatRoom) -> ChatMembership:
        if self.membership is None:
            raise HTTPException(status_code=403, detail="nope")
        return self.membership


def _membership(role: str, *, write: bool = True, moderate: bool = False) -> ChatMembership:
    return ChatMembership(role=role, display_name=role.title(), can_write=write, can_moderate=moderate)


SPECTATOR = _membership("spectator", write=False)
CAPTAIN_MEMBER = _membership("captain")
STAFF_MEMBER = _membership("staff", moderate=True)


def _row(message_id: int, *, auth_user_id: int = 7, body: str = "hi") -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        created_at=datetime.now(UTC),
        auth_user_id=auth_user_id,
        author_name="Fox",
        author_role="captain",
        body=body,
        deleted_at=None,
        deleted_by_auth_user_id=None,
    )


class ChatServiceTest(IsolatedAsyncioTestCase):
    def _service(
        self,
        access: _Access,
        *,
        messages: _Messages | None = None,
        settings: _Settings | None = None,
        mutes: _Mutes | None = None,
    ) -> tuple[ChatService, _Messages, _Settings, _Mutes]:
        messages = messages or _Messages()
        settings = settings if settings is not None else _Settings()
        mutes = mutes or _Mutes()
        service = ChatService(access, messages=messages, settings=settings, mutes=mutes)
        return service, messages, settings, mutes

    # ── spectator visibility ─────────────────────────────────────────────────

    async def test_draft_spectator_reads_by_default(self) -> None:
        """A draft is a show. With no settings row, watchers get the chat."""
        service, *_ = self._service(_Access(SPECTATOR))
        envelope = await service.envelope(_Session(), VIEWER, ChatRoom.draft(3))
        self.assertEqual(envelope.viewer.role, "spectator")
        self.assertFalse(envelope.viewer.can_write)
        self.assertTrue(envelope.settings.spectators_can_read)

    async def test_pregame_spectator_is_refused_by_default(self) -> None:
        """The pre-game room is where lobby codes are exchanged."""
        service, *_ = self._service(_Access(SPECTATOR))
        with self.assertRaises(HTTPException) as caught:
            await service.envelope(_Session(), VIEWER, ChatRoom.encounter(42))
        self.assertEqual(caught.exception.status_code, 403)

    async def test_organizer_can_open_the_pregame_chat(self) -> None:
        service, *_ = self._service(_Access(SPECTATOR), settings=_Settings(True))
        envelope = await service.envelope(_Session(), VIEWER, ChatRoom.encounter(42))
        self.assertTrue(envelope.settings.spectators_can_read)

    async def test_organizer_can_close_the_draft_chat(self) -> None:
        service, *_ = self._service(_Access(SPECTATOR), settings=_Settings(False))
        with self.assertRaises(HTTPException):
            await service.envelope(_Session(), VIEWER, ChatRoom.draft(3))

    async def test_spectator_never_writes_even_when_the_room_is_open(self) -> None:
        service, *_ = self._service(_Access(SPECTATOR))
        with patch("shared.services.chat.service.emit"):
            with self.assertRaises(HTTPException) as caught:
                await service.post(_Session(), VIEWER, ChatRoom.draft(3), "hello")
        self.assertEqual(caught.exception.status_code, 403)

    # ── writing ──────────────────────────────────────────────────────────────

    async def test_post_emits_a_non_durable_message_on_the_room_topic(self) -> None:
        service, messages, *_ = self._service(_Access(CAPTAIN_MEMBER))
        session = _Session()
        with patch("shared.services.chat.service.emit") as emit:
            message = await service.post(session, CAPTAIN, ChatRoom.draft(3), "  ready?  ")

        self.assertEqual(message.body, "ready?")
        self.assertEqual(message.author_role, "captain")
        self.assertEqual(session.commits, 1)
        kwargs = emit.await_args.kwargs
        self.assertEqual(kwargs["scope"].domain_topic("chat"), "draft:3:chat")
        self.assertEqual(kwargs["data"].event_type, EVENT_MESSAGE)
        self.assertFalse(kwargs["data"].durable)
        self.assertEqual(kwargs["actor_user_id"], CAPTAIN.id)
        self.assertEqual(messages.rows[-1].body, "ready?")

    async def test_blank_and_oversized_bodies_are_refused_without_writing(self) -> None:
        for body in ("", "   ", "\x00\x07", "x" * 501, "y" * 2001):
            with self.subTest(body=body[:12]):
                service, messages, *_ = self._service(_Access(CAPTAIN_MEMBER))
                with patch("shared.services.chat.service.emit") as emit:
                    with self.assertRaises(HTTPException) as caught:
                        await service.post(_Session(), CAPTAIN, ChatRoom.draft(3), body)
                self.assertEqual(caught.exception.status_code, 422)
                self.assertEqual(messages.rows, [])
                emit.assert_not_awaited()

    async def test_throttled_author_gets_429(self) -> None:
        service, *_ = self._service(_Access(CAPTAIN_MEMBER), messages=_Messages(throttled=True))
        with patch("shared.services.chat.service.emit"):
            with self.assertRaises(HTTPException) as caught:
                await service.post(_Session(), CAPTAIN, ChatRoom.draft(3), "spam")
        self.assertEqual(caught.exception.status_code, 429)

    # ── mutes ────────────────────────────────────────────────────────────────

    async def test_muted_captain_is_refused_with_a_coded_error(self) -> None:
        mute = SimpleNamespace(auth_user_id=CAPTAIN.id, muted_until=None, reason=None)
        service, messages, _s, _m = self._service(_Access(CAPTAIN_MEMBER), mutes=_Mutes(mute))
        with patch("shared.services.chat.service.emit"):
            with self.assertRaises(HTTPException) as caught:
                await service.post(_Session(), CAPTAIN, ChatRoom.draft(3), "hello")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail[0]["code"], "chat_muted")
        self.assertEqual(messages.rows, [])

    async def test_envelope_tells_a_muted_viewer_they_cannot_write(self) -> None:
        until = datetime.now(UTC) + timedelta(minutes=5)
        mute = SimpleNamespace(
            auth_user_id=CAPTAIN.id,
            muted_until=until,
            reason="spam",
            created_by_auth_user_id=STAFF.id,
            created_at=datetime.now(UTC),
        )
        service, *_ = self._service(_Access(CAPTAIN_MEMBER), mutes=_Mutes(mute))
        envelope = await service.envelope(_Session(), CAPTAIN, ChatRoom.draft(3))
        self.assertFalse(envelope.viewer.can_write)
        self.assertEqual(envelope.viewer.muted_until, until)
        self.assertEqual(envelope.mutes, [])  # not a moderator: the list stays private

    async def test_only_moderators_see_the_mute_list(self) -> None:
        mute = SimpleNamespace(
            auth_user_id=CAPTAIN.id,
            muted_until=None,
            reason=None,
            created_by_auth_user_id=STAFF.id,
            created_at=datetime.now(UTC),
        )
        service, *_ = self._service(_Access(STAFF_MEMBER), mutes=_Mutes(mute))
        envelope = await service.envelope(_Session(), STAFF, ChatRoom.draft(3))
        self.assertEqual([m.auth_user_id for m in envelope.mutes], [CAPTAIN.id])

    async def test_captain_cannot_mute(self) -> None:
        service, *_ = self._service(_Access(CAPTAIN_MEMBER))
        with patch("shared.services.chat.service.emit"):
            with self.assertRaises(HTTPException) as caught:
                await service.set_mute(_Session(), CAPTAIN, ChatRoom.draft(3), VIEWER.id, minutes=5, reason=None)
        self.assertEqual(caught.exception.status_code, 403)

    async def test_staff_mute_emits_and_stores_a_deadline(self) -> None:
        service, _msg, _set, mutes = self._service(_Access(STAFF_MEMBER))
        with patch("shared.services.chat.service.emit") as emit:
            mute = await service.set_mute(_Session(), STAFF, ChatRoom.draft(3), CAPTAIN.id, minutes=5, reason="spam")
        self.assertIsNotNone(mute.muted_until)
        self.assertEqual(mutes.set_calls[0]["auth_user_id"], CAPTAIN.id)
        self.assertEqual(emit.await_args.kwargs["data"].event_type, EVENT_MUTED)

    # ── deletion ─────────────────────────────────────────────────────────────

    async def test_captain_deletes_own_message_but_not_the_opponents(self) -> None:
        rows = [_row(1, auth_user_id=CAPTAIN.id), _row(2, auth_user_id=VIEWER.id)]
        service, messages, *_ = self._service(_Access(CAPTAIN_MEMBER), messages=_Messages(rows))

        with patch("shared.services.chat.service.emit") as emit:
            await service.delete(_Session(), CAPTAIN, ChatRoom.draft(3), 1)
        self.assertEqual(messages.deleted, [(1, CAPTAIN.id)])
        self.assertEqual(emit.await_args.kwargs["data"].event_type, EVENT_DELETED)

        with patch("shared.services.chat.service.emit"):
            with self.assertRaises(HTTPException) as caught:
                await service.delete(_Session(), CAPTAIN, ChatRoom.draft(3), 2)
        self.assertEqual(caught.exception.status_code, 403)

    async def test_staff_deletes_anyones_message(self) -> None:
        service, messages, *_ = self._service(
            _Access(STAFF_MEMBER), messages=_Messages([_row(1, auth_user_id=CAPTAIN.id)])
        )
        with patch("shared.services.chat.service.emit"):
            await service.delete(_Session(), STAFF, ChatRoom.draft(3), 1)
        self.assertEqual(messages.deleted, [(1, STAFF.id)])

    async def test_deleting_a_message_of_another_room_is_a_404(self) -> None:
        service, *_ = self._service(_Access(STAFF_MEMBER), messages=_Messages([]))
        with patch("shared.services.chat.service.emit"):
            with self.assertRaises(HTTPException) as caught:
                await service.delete(_Session(), STAFF, ChatRoom.draft(3), 77)
        self.assertEqual(caught.exception.status_code, 404)

    # ── visibility toggle ────────────────────────────────────────────────────

    async def test_toggle_emits_the_event_the_gateway_revokes_on(self) -> None:
        service, _m, settings, _mu = self._service(_Access(STAFF_MEMBER), settings=_Settings(True))
        with patch("shared.services.chat.service.emit") as emit:
            result = await service.set_settings(_Session(), STAFF, ChatRoom.draft(3), spectators_can_read=False)
        self.assertFalse(result.spectators_can_read)
        self.assertEqual(settings.writes, [False])
        self.assertEqual(emit.await_args.kwargs["data"].event_type, EVENT_VISIBILITY)

    async def test_toggle_to_the_current_value_writes_and_emits_nothing(self) -> None:
        """The gateway re-authorizes every subscriber on that event."""
        service, _m, settings, _mu = self._service(_Access(STAFF_MEMBER), settings=_Settings(True))
        with patch("shared.services.chat.service.emit") as emit:
            await service.set_settings(_Session(), STAFF, ChatRoom.draft(3), spectators_can_read=True)
        self.assertEqual(settings.writes, [])
        emit.assert_not_awaited()

    async def test_a_refused_resolver_refuses_every_verb(self) -> None:
        service, *_ = self._service(_Access(None))
        room = ChatRoom.draft(3)
        with patch("shared.services.chat.service.emit"):
            for call in (
                service.envelope(_Session(), VIEWER, room),
                service.post(_Session(), VIEWER, room, "hi"),
                service.delete(_Session(), VIEWER, room, 1),
                service.set_settings(_Session(), VIEWER, room, spectators_can_read=True),
            ):
                with self.assertRaises(HTTPException):
                    await call
