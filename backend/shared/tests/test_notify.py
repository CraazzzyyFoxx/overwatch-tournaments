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
the fixture tears down.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from pydantic import ValidationError

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))

from shared.services.notifications import notify  # noqa: E402
from shared.services.realtime import Resource, Scope  # noqa: E402
from shared.services.realtime.emit import _STAGED_KEY  # noqa: E402

_INVITE = {
    "team_id": 12,
    "team_name": "Anak",
    "tournament_id": 3,
    "tournament_name": "OWT Season 5",
    "slot_code": "dps1",
    "is_substitute": False,
    "invite_id": 99,
}


class _Session:
    """Records the three session methods the helper could reach for.

    ``commit``/``flush`` exist only so that calling them would be *visible*;
    the tests assert they stay untouched.
    """

    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = 0
        self.flushed = 0
        # ``emit`` hangs its staged events here, the same way SQLAlchemy's
        # Session.info does.
        self.info: dict[str, object] = {}

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1


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

        self.assertEqual([row], session.added)
        self.assertEqual("team_invite.received", row.kind)
        self.assertEqual(7, row.recipient_auth_user_id)
        self.assertEqual(12, row.payload_json["team_id"])
        self.assertEqual(0, session.committed)
        self.assertEqual(0, session.flushed)

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
