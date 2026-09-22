"""Behavioural pins for the single write path of the notification inbox.

``notify()`` is the only thing in the project allowed to append a
``notification`` row, so everything a caller can get wrong has to fail here
rather than at the database: an unknown ``kind`` (the frontend has no message
for it), a payload missing a field the rendered message interpolates, an
audience that disagrees with the recipient columns the CHECK constraints
enforce, or an announcement published to the whole platform in one language.

The session is a spy rather than a real engine on purpose: the invariant under
test is *that the caller's transaction still owns the commit*, which a real
session cannot show -- committing would look identical to not committing once
the fixture tears down. It does answer ``flush`` (assigning ids, as the
database would) and ``scalar`` (the dedupe lookup), because a personal row now
needs its id for the delivery event.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from pydantic import ValidationError

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))

from shared.messaging.config import NOTIFICATIONS_EXCHANGE  # noqa: E402
from shared.models.platform.notification import Notification  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.services.notifications import (  # noqa: E402
    BROADCASTABLE_KINDS,
    NOTIFICATION_KIND_GROUPS,
    NOTIFICATION_KINDS,
    broadcast,
    effective_discord_dm,
    notify,
    wants_discord_dm,
)
from shared.services.realtime import Resource, Scope  # noqa: E402
from shared.services.realtime.emit import _STAGED_KEY  # noqa: E402

_INVITE = {
    "team_id": 12,
    "team_name": "Anak",
    "tournament_id": 3,
    "tournament_name": "OWT Season 5",
    "slot_code": "damage1",
    "is_substitute": False,
    "invite_id": 99,
}


class _Session:
    """Records the session methods the helper could reach for.

    ``commit`` exists only so that calling it would be *visible*; the tests
    assert it stays untouched. ``flush`` stamps ids the way the database would.
    ``scalar`` answers the dedupe lookup with ``existing``.
    """

    def __init__(self, existing: Notification | None = None) -> None:
        self.added: list[object] = []
        self.committed = 0
        self.flushed = 0
        self.lookups = 0
        self.existing = existing
        # ``emit`` hangs its staged events here, the same way SQLAlchemy's
        # Session.info does.
        self.info: dict[str, object] = {}

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1
        for index, row in enumerate(self.added, start=1):
            if getattr(row, "id", None) is None:
                row.id = 100 + index

    async def scalar(self, statement: object) -> Notification | None:
        self.lookups += 1
        return self.existing

    def notifications(self) -> list[Notification]:
        return [row for row in self.added if isinstance(row, Notification)]

    def outbox(self) -> list[EventOutbox]:
        return [row for row in self.added if isinstance(row, EventOutbox)]


class RealtimeSignalTests(IsolatedAsyncioTestCase):
    async def test_a_personal_row_stages_one_invalidation_and_one_signal(self) -> None:
        session = _Session()

        await notify(
            session,
            kind="team_invite.received",
            payload=dict(_INVITE),
            audience="user",
            recipient_auth_user_id=7,
            actor_auth_user_id=3,
        )

        staged = session.info[_STAGED_KEY]
        self.assertEqual({Scope.user(7): ({Resource.USER_NOTIFICATIONS}, {})}, staged.invalidations)
        ((scope, data, actor),) = staged.domain
        self.assertEqual(Scope.user(7), scope)
        self.assertEqual("notifications", data.domain)
        self.assertEqual("notification.created", data.event_type)
        # Non-durable and empty: the inbox read is the authorized channel, and a
        # reconnecting client refetches it anyway.
        self.assertFalse(data.durable)
        self.assertEqual({}, dict(data.payload))
        self.assertEqual(3, actor)

    async def test_an_announcement_signals_nobody(self) -> None:
        # Audience-wide rows have no user topic to land on; the banner query is
        # how they are read.
        session = _Session()

        await notify(
            session,
            kind="announcement.published",
            payload={"locales": {"ru": {"title": "Сбор"}}, "default_locale": "ru"},
            audience="workspace",
            workspace_id=4,
        )

        self.assertNotIn(_STAGED_KEY, session.info)


class NotifyTests(IsolatedAsyncioTestCase):
    async def test_notify_does_not_commit(self) -> None:
        session = _Session()

        row = await notify(
            session,
            kind="team_invite.received",
            payload=dict(_INVITE),
            audience="user",
            recipient_auth_user_id=7,
        )

        self.assertEqual([row], session.notifications())
        self.assertEqual("team_invite.received", row.kind)
        self.assertEqual(7, row.recipient_auth_user_id)
        self.assertEqual(12, row.payload_json["team_id"])
        self.assertEqual(0, session.committed)

    async def test_unknown_kind_is_rejected(self) -> None:
        session = _Session()

        with self.assertRaises(ValueError) as caught:
            await notify(
                session,
                kind="nope.nope",
                payload={},
                audience="user",
                recipient_auth_user_id=7,
            )

        self.assertIn("nope.nope", str(caught.exception))
        self.assertEqual([], session.added)

    async def test_payload_is_validated_against_kind_schema(self) -> None:
        session = _Session()
        without_team = {k: v for k, v in _INVITE.items() if k != "team_id"}

        with self.assertRaises(ValidationError) as caught:
            await notify(
                session,
                kind="team_invite.received",
                payload=without_team,
                audience="user",
                recipient_auth_user_id=7,
            )

        self.assertIn("team_id", str(caught.exception))
        self.assertEqual([], session.added)

    async def test_global_announcement_requires_every_locale(self) -> None:
        session = _Session()
        ru_only = {"locales": {"ru": {"title": "Обновление"}}, "default_locale": "ru"}

        with self.assertRaises(ValidationError) as caught:
            await notify(session, kind="announcement.published", payload=ru_only, audience="global")

        self.assertIn("en", str(caught.exception))
        self.assertEqual([], session.added)

        row = await notify(
            session,
            kind="announcement.published",
            payload={
                "locales": {"ru": {"title": "Обновление"}, "en": {"title": "Update"}},
                "default_locale": "ru",
            },
            audience="global",
        )

        self.assertEqual("global", row.audience)
        self.assertEqual({"ru", "en"}, set(row.payload_json["locales"]))

    async def test_workspace_announcement_accepts_one_locale(self) -> None:
        session = _Session()

        row = await notify(
            session,
            kind="announcement.published",
            payload={"locales": {"ru": {"title": "Сбор"}}, "default_locale": "ru"},
            audience="workspace",
            workspace_id=4,
        )

        self.assertEqual("workspace", row.audience)
        self.assertEqual(4, row.workspace_id)
        self.assertEqual(["ru"], list(row.payload_json["locales"]))

    async def test_default_locale_must_be_present(self) -> None:
        session = _Session()

        with self.assertRaises(ValidationError) as caught:
            await notify(
                session,
                kind="announcement.published",
                payload={"locales": {"ru": {"title": "Сбор"}}, "default_locale": "en"},
                audience="workspace",
                workspace_id=4,
            )

        self.assertIn("default_locale", str(caught.exception))
        self.assertEqual([], session.added)

    async def test_user_audience_requires_recipient(self) -> None:
        session = _Session()

        with self.assertRaises(ValueError):
            await notify(
                session,
                kind="team_invite.received",
                payload=dict(_INVITE),
                audience="user",
            )

        self.assertEqual([], session.added)

    async def test_a_protocol_relative_href_is_not_a_site_path(self) -> None:
        """``//evil.com`` starts with a slash and still leaves the site.

        The banner renders the href as an anchor target on a page every visitor
        of the platform sees, so a link that reads as internal and lands on a
        third-party domain is an open redirect with the platform's own branding
        around it.
        """
        session = _Session()

        for href in ("//evil.com", "/\\evil.com"):
            with self.assertRaises(ValidationError, msg=href):
                await notify(
                    session,
                    kind="announcement.published",
                    payload={
                        "locales": {"ru": {"title": "Сбор"}},
                        "default_locale": "ru",
                        "href": href,
                    },
                    audience="workspace",
                    workspace_id=4,
                )

        self.assertEqual([], session.added)

        row = await notify(
            session,
            kind="announcement.published",
            payload={
                "locales": {"ru": {"title": "Сбор"}},
                "default_locale": "ru",
                "href": "/changelog/2026-09",
            },
            audience="workspace",
            workspace_id=4,
        )

        self.assertEqual("/changelog/2026-09", row.payload_json["href"])

    async def test_control_characters_cannot_smuggle_a_protocol_relative_href(self) -> None:
        """A browser strips tab, CR and LF out of a URL before resolving it.

        So ``"/\\t/evil.com"`` passes a "starts with one slash" check while the
        browser navigates to ``//evil.com`` -- the same open redirect the check
        above rejects, wearing one throwaway control character as a disguise.
        """
        session = _Session()

        for href in ("/\t/evil.com", "/\n/evil.com", "/\r/evil.com", "/ /evil.com", "/ok\tx"):
            with self.assertRaises(ValidationError, msg=repr(href)):
                await notify(
                    session,
                    kind="announcement.published",
                    payload={
                        "locales": {"ru": {"title": "Сбор"}},
                        "default_locale": "ru",
                        "href": href,
                    },
                    audience="workspace",
                    workspace_id=4,
                )

        self.assertEqual([], session.added)


class DeliveryEventTests(IsolatedAsyncioTestCase):
    """A personal row carries its own delivery event; nothing else does."""

    async def test_a_personal_row_enqueues_its_created_event(self) -> None:
        session = _Session()

        row = await notify(
            session,
            kind="team_invite.received",
            payload=dict(_INVITE),
            audience="user",
            recipient_auth_user_id=7,
        )

        (event,) = session.outbox()
        self.assertIsNotNone(row.id)
        self.assertEqual(row.id, event.payload_json["notification_id"])
        self.assertEqual("notification.created", event.routing_key)
        self.assertEqual(NOTIFICATIONS_EXCHANGE.name, event.exchange)

    async def test_a_workspace_row_enqueues_nothing(self) -> None:
        session = _Session()

        await notify(
            session,
            kind="registration.opened",
            payload={"tournament_id": 3, "tournament_name": "OWT Season 5"},
            audience="workspace",
            workspace_id=4,
        )

        self.assertEqual(1, len(session.notifications()))
        self.assertEqual([], session.outbox())


class DedupeKeyTests(IsolatedAsyncioTestCase):
    async def test_a_repeat_returns_the_existing_row_and_writes_nothing(self) -> None:
        first = Notification(id=55, kind="check_in.opened", dedupe_key="tournament:3")
        session = _Session(existing=first)

        row = await notify(
            session,
            kind="check_in.opened",
            payload={"tournament_id": 3, "tournament_name": "OWT Season 5"},
            audience="user",
            recipient_auth_user_id=7,
            dedupe_key="tournament:3",
        )

        self.assertIs(first, row)
        self.assertEqual([], session.added)
        # No inbox signal and no delivery for a row nobody wrote.
        self.assertNotIn(_STAGED_KEY, session.info)

    async def test_a_first_occurrence_is_written_with_its_key(self) -> None:
        session = _Session(existing=None)

        row = await notify(
            session,
            kind="check_in.opened",
            payload={"tournament_id": 3, "tournament_name": "OWT Season 5"},
            audience="user",
            recipient_auth_user_id=7,
            dedupe_key="tournament:3",
        )

        self.assertEqual(1, session.lookups)
        self.assertEqual([row], session.notifications())
        self.assertEqual("tournament:3", row.dedupe_key)
        self.assertEqual(1, len(session.outbox()))

    async def test_no_key_never_looks_up(self) -> None:
        # An invite sent again is a legitimate repeat.
        session = _Session(existing=Notification(id=1))

        await notify(
            session,
            kind="team_invite.received",
            payload=dict(_INVITE),
            audience="user",
            recipient_auth_user_id=7,
        )

        self.assertEqual(0, session.lookups)
        self.assertEqual(1, len(session.notifications()))


class BroadcastTests(IsolatedAsyncioTestCase):
    async def test_broadcast_enqueues_a_validated_snapshot_and_no_row(self) -> None:
        session = _Session()

        await broadcast(
            session,
            kind="registration.opened",
            payload={"tournament_id": 3, "tournament_name": "OWT Season 5", "closes_at": None},
            workspace_id=4,
            dedupe_key="tournament:3",
        )

        self.assertEqual([], session.notifications())
        (event,) = session.outbox()
        self.assertEqual("notification.broadcast", event.routing_key)
        self.assertEqual(4, event.payload_json["workspace_id"])
        self.assertEqual("tournament:3", event.payload_json["dedupe_key"])
        # Same snapshot rules as the inbox row: absent optionals are dropped.
        self.assertEqual({"tournament_id": 3, "tournament_name": "OWT Season 5"}, event.payload_json["payload"])
        self.assertEqual(0, session.committed)

    async def test_broadcast_rejects_a_personal_kind(self) -> None:
        session = _Session()

        with self.assertRaises(ValueError):
            await broadcast(
                session,
                kind="team_invite.received",
                payload=dict(_INVITE),
                workspace_id=4,
                dedupe_key="x",
            )

        self.assertEqual([], session.added)

    async def test_broadcast_validates_the_payload(self) -> None:
        session = _Session()

        with self.assertRaises(ValidationError):
            await broadcast(
                session,
                kind="encounter.scheduled",
                payload={"encounter_id": 1, "tournament_id": 3},
                workspace_id=4,
                dedupe_key="encounter:1",
            )

        self.assertEqual([], session.added)


class DiscordDmGroupTests(IsolatedAsyncioTestCase):
    def test_every_personal_kind_has_exactly_one_group(self) -> None:
        # A kind outside every group is silently never DMed; one that is not a
        # registered kind is a typo.
        never_personal = {"registration.opened", "announcement.published"}
        self.assertEqual(set(NOTIFICATION_KINDS) - never_personal, set(NOTIFICATION_KIND_GROUPS))
        self.assertTrue(BROADCASTABLE_KINDS <= set(NOTIFICATION_KINDS))

    def test_groups_default_on_and_honour_an_opt_out(self) -> None:
        self.assertEqual({"tournament": True, "matches": True, "team": True}, effective_discord_dm({}))
        self.assertTrue(wants_discord_dm({}, "encounter.scheduled"))
        self.assertFalse(wants_discord_dm({"matches": False}, "encounter.scheduled"))
        self.assertTrue(wants_discord_dm({"matches": False}, "check_in.opened"))
        # Not personal: never DMed, whatever is stored.
        self.assertFalse(wants_discord_dm({}, "registration.opened"))
        # Garbage in the JSONB is not an opt-out.
        self.assertTrue(wants_discord_dm({"team": "no"}, "team.kicked"))


_TEAM_EVENT = {
    "team_id": 12,
    "team_name": "Anak",
    "tournament_id": 3,
    "tournament_name": "OWT Season 5",
}


class TeamRosterKindTests(IsolatedAsyncioTestCase):
    async def test_kicked_and_disbanded_share_the_roster_snapshot(self) -> None:
        for kind in ("team.kicked", "team.disbanded"):
            with self.subTest(kind=kind):
                session = _Session()
                row = await notify(
                    session,
                    kind=kind,
                    payload=dict(_TEAM_EVENT),
                    audience="user",
                    recipient_auth_user_id=7,
                )
                self.assertEqual(kind, row.kind)
                self.assertEqual("Anak", row.payload_json["team_name"])

    async def test_rejected_carries_an_optional_reason(self) -> None:
        session = _Session()
        row = await notify(
            session,
            kind="team.rejected",
            payload={**_TEAM_EVENT, "reason": "Duplicate roster"},
            audience="user",
            recipient_auth_user_id=7,
        )
        self.assertEqual("Duplicate roster", row.payload_json["reason"])
