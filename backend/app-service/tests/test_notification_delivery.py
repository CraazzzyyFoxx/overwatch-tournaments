"""Behavioural pins for Discord delivery: what is rendered, and what is sent.

Two halves, one file, because they are one contract. The render half needs no
database at all -- it is a pure function over a payload snapshot -- and pins the
three things a template can silently get wrong: a kind with no translation, a
team name that italicises the rest of the line, and a link that points somewhere
the inbox does not.

The delivery half runs against a real (in-memory) SQLite engine behind the
sync-``Session`` shim the sibling notification suites established, because every
assertion here is about *rows*: the ledger row that makes a redelivered event
send nothing, and the outbox row that is the message. A mock session would
happily agree with a flow that inserts nothing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import models  # noqa: E402
from shared.models.identity.oauth import OAuthConnection  # noqa: E402
from shared.models.platform.notification import (  # noqa: E402
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationWorkspaceConfig,
)
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.schemas.events import NotificationBroadcastEvent, NotificationCreatedEvent  # noqa: E402
from shared.services.notifications import NOTIFICATION_KINDS  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src.core import db  # noqa: E402
from src.domain.notification_render import TEMPLATES, deep_link_path, render_discord  # noqa: E402
from src.services.notification_delivery import consumer  # noqa: E402
from src.services.notification_delivery.service import NotificationDeliveryService  # noqa: E402

install_postgres_type_shims()

TABLES = (
    Notification.__table__,
    NotificationDelivery.__table__,
    NotificationPreference.__table__,
    NotificationWorkspaceConfig.__table__,
    EventOutbox.__table__,
    OAuthConnection.__table__,
    models.Workspace.__table__,
    models.Tournament.__table__,
)

SITE = "https://owt.example"
RECIPIENT = 100
WORKSPACE = 7
DISCORD_ID = "424242424242424242"
CHANNEL_ID = 987654321098765432

DEADLINE = "2026-09-25T18:00:00+00:00"
# 2026-09-25T18:00:00Z as Discord reads it.
DEADLINE_UNIX = int(datetime(2026, 9, 25, 18, 0, tzinfo=UTC).timestamp())


class RenderTests(IsolatedAsyncioTestCase):
    """The templates themselves -- no session, no broker."""

    def test_every_deliverable_kind_is_translated_in_both_locales(self) -> None:
        """A kind without a template is a notification that silently never sends.

        ``announcement.published`` is the one exception: operator text already
        carries its own copy and never leaves the app.
        """
        deliverable = set(NOTIFICATION_KINDS) - {"announcement.published"}

        for locale in ("ru", "en"):
            self.assertEqual(set(TEMPLATES[locale]), deliverable, locale)

    def test_user_written_text_cannot_style_the_message(self) -> None:
        """Team, tournament and workspace names and rejection reasons are typed
        by people, and a card is markdown end to end.

        A masked link is the dangerous one: unescaped, it becomes a clickable
        ``Claim prize`` inside the platform's own DM. ``#`` would make a
        headline, ``<@id>`` a mention, ``*`` italicise the rest of the line.
        """
        card = render_discord(
            "team.rejected",
            {
                "team_id": 1,
                "team_name": "[Claim prize](https://evil.example)",
                "tournament_id": 3,
                "tournament_name": "# Cup <@1>",
                "reason": "_no show_",
            },
            locale="ru",
            site_url=SITE,
            workspace_name="*Org*",
        )

        self.assertIn(r"\[Claim prize\](https://evil.example)", card.text)
        self.assertIn(r"\# Cup \<@1\>", card.text)
        self.assertIn(r"-# \*Org\*", card.text)
        self.assertIn(r"\_no show\_", card.details)

    def test_no_reason_is_too_long_for_one_message(self) -> None:
        # Discord answers 400 past 4000 characters of card text, which would
        # park the command in the DLQ instead of sending it.
        card = render_discord(
            "team.rejected",
            {
                "team_id": 1,
                "team_name": "*" * 400,
                "tournament_id": 3,
                "tournament_name": "_" * 400,
                "reason": "*" * 5000,
            },
            locale="en",
            site_url=SITE,
            workspace_name="#" * 400,
        )

        self.assertLessEqual(len(card.text) + len(card.details or ""), 4000)
        self.assertTrue(card.details.endswith("…"))

    def test_the_card_wears_the_colour_of_its_news(self) -> None:
        """Same palette as the inbox: an approval must not look like a rejection."""
        payload = {"tournament_id": 3, "tournament_name": "Cup", "registration_id": 1}
        approved = render_discord("registration.approved", payload, locale="ru", site_url=SITE)
        rejected = render_discord("registration.rejected", payload, locale="ru", site_url=SITE)
        answer = {"team_id": 1, "team_name": "T", "invite_id": 1, "responder_name": "R"}
        accepted = render_discord("team_invite.answered", {**answer, "answer": "accepted"}, locale="ru", site_url=SITE)
        declined = render_discord("team_invite.answered", {**answer, "answer": "declined"}, locale="ru", site_url=SITE)

        self.assertEqual(approved.accent_color, accepted.accent_color)
        self.assertEqual(rejected.accent_color, declined.accent_color)
        self.assertNotEqual(approved.accent_color, rejected.accent_color)

    def test_times_are_rendered_in_the_readers_timezone(self) -> None:
        """``<t:UNIX:F> (<t:UNIX:R>)`` -- Discord localises it per reader."""
        card = render_discord(
            "encounter.scheduled",
            {
                "encounter_id": 5,
                "tournament_id": 3,
                "tournament_name": "Cup",
                "home_team_name": "A",
                "away_team_name": "B",
                "scheduled_at": DEADLINE,
            },
            locale="en",
            site_url=SITE,
        )

        self.assertIn(f"<t:{DEADLINE_UNIX}:F> (<t:{DEADLINE_UNIX}:R>)", card.details)

    def test_a_missing_optional_field_drops_its_line(self) -> None:
        """``closes_at`` is absent from the snapshot when the phase has no end,
        and an organizer may reject a team without writing a reason."""
        payload = {"tournament_id": 3, "tournament_name": "Cup"}
        team = {"team_id": 1, "team_name": "T", **payload}

        open_ended = render_discord("check_in.opened", payload, locale="ru", site_url=SITE)
        with_deadline = render_discord(
            "check_in.opened", {**payload, "closes_at": DEADLINE}, locale="ru", site_url=SITE
        )
        no_reason = render_discord("team.rejected", {**team, "reason": ""}, locale="ru", site_url=SITE)

        self.assertIsNone(open_ended.details)
        self.assertIn(f"<t:{DEADLINE_UNIX}:F>", with_deadline.details)
        self.assertIsNone(no_reason.details)

    def test_links_land_where_the_inbox_lands(self) -> None:
        """The paths are duplicated from ``lib/notifications/href.ts`` by hand.

        Pinned here so a drift is a failing test rather than a DM that opens
        a different screen than the bell did.
        """
        cases = {
            "team_invite.received": "/tournaments/3/participants",
            "registration.approved": "/tournaments/3/participants",
            "registration.rejected": "/tournaments/3/participants",
            "team.kicked": "/tournaments/3/participants",
            "team.rejected": "/tournaments/3/participants",
            "team.disbanded": "/tournaments/3/participants",
            "encounter.report_disputed": "/tournaments/3/pregame/5",
            "encounter.scheduled": "/tournaments/3/pregame/5",
            "registration.opened": "/tournaments/3",
            "check_in.opened": "/tournaments/3",
            "team_invite.answered": None,
        }
        payload = {"tournament_id": 3, "encounter_id": 5}

        for kind, expected in cases.items():
            self.assertEqual(deep_link_path(kind, payload), expected, kind)

    def test_links_are_absolute_and_only_a_dm_offers_the_way_out(self) -> None:
        """A channel post has no single reader whose DMs could be switched off."""
        payload = {"tournament_id": 3, "tournament_name": "Cup"}

        post = render_discord("check_in.opened", payload, locale="en", site_url=f"{SITE}/")
        dm = render_discord("check_in.opened", payload, locale="en", site_url=SITE, personal=True)

        post_onward, dm_onward = post.rows[-1], dm.rows[-1]
        self.assertEqual([button.url for button in post_onward], [f"{SITE}/tournaments/3"])
        link, menu = dm_onward
        self.assertEqual(link.url, f"{SITE}/tournaments/3")
        # Only a trigger: the switch itself is shown to the reader alone, by the bot.
        self.assertEqual((menu.action, menu.target), ("notifications.menu", "all"))

    def test_one_click_answers_name_the_object_they_act_on(self) -> None:
        """The bot answers a button with ``owt:<action>:<target>``; a wrong target
        is an invite accepted on the wrong team or a check-in to another event."""
        invite = render_discord(
            "team_invite.received",
            {
                "team_id": 1,
                "team_name": "T",
                "tournament_id": 3,
                "tournament_name": "Cup",
                "slot_code": "tank",
                "is_substitute": False,
                "invite_id": 42,
            },
            locale="ru",
            site_url=SITE,
        )
        check_in = render_discord(
            "check_in.opened", {"tournament_id": 3, "tournament_name": "Cup"}, locale="ru", site_url=SITE
        )
        opened = render_discord(
            "registration.opened", {"tournament_id": 3, "tournament_name": "Cup"}, locale="ru", site_url=SITE
        )

        self.assertEqual(
            [(b.action, b.target) for b in invite.answers], [("invite.accept", "42"), ("invite.decline", "42")]
        )
        self.assertEqual(
            [(b.action, b.target) for b in check_in.answers], [("check_in", "3"), ("registration.view", "3")]
        )
        # Registering needs the form: that card only links to it.
        self.assertEqual(opened.answers, [])
        self.assertEqual([b.type for row in opened.rows for b in row], ["link"])

    def test_only_an_absolute_image_becomes_the_thumbnail(self) -> None:
        """Discord fetches the thumbnail itself; a site-relative path is a 400."""
        payload = {"tournament_id": 3, "tournament_name": "Cup"}

        remote = render_discord("check_in.opened", payload, locale="en", site_url=SITE, image_url="https://cdn/x.png")
        relative = render_discord("check_in.opened", payload, locale="en", site_url=SITE, image_url="/x.png")

        self.assertEqual(remote.thumbnail_url, "https://cdn/x.png")
        self.assertIsNone(relative.thumbnail_url)


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` -- no async SQLite driver."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()


class _SessionMaker:
    """Stands in for ``db.async_session_maker`` (one shared shim per test)."""

    def __init__(self, shim: _AsyncSessionShim) -> None:
        self._shim = shim

    def __call__(self) -> _SessionMaker:
        return self

    async def __aenter__(self) -> _AsyncSessionShim:
        return self._shim

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Message:
    """The few attributes ``observe_message_processing`` reads off a message."""

    headers: dict[str, str] = {}
    message_id = None
    correlation_id = None
    raw_message = None


class DeliveryTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in TABLES if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in TABLES:
                table.create(conn)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.shim = _AsyncSessionShim(self.session)
        self.service = NotificationDeliveryService()

    # -- builders ---------------------------------------------------------

    def personal(self, kind: str = "check_in.opened", **values: Any) -> Notification:
        row = Notification(
            audience="user",
            recipient_auth_user_id=RECIPIENT,
            source_workspace_id=WORKSPACE,
            kind=kind,
            payload_json={"tournament_id": 3, "tournament_name": "Cup"},
            **values,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def link_discord(self, provider_user_id: str = DISCORD_ID) -> None:
        self.session.add(
            OAuthConnection(
                auth_user_id=RECIPIENT,
                provider="discord",
                provider_user_id=provider_user_id,
                username="player",
            )
        )
        self.session.flush()

    def configure_workspace(self, *, channel_id: int | None = CHANNEL_ID, kinds: list[str] | None = None) -> None:
        self.session.add(
            NotificationWorkspaceConfig(
                workspace_id=WORKSPACE,
                discord_channel_id=channel_id,
                locale="en",
                broadcast_kinds=["registration.opened"] if kinds is None else kinds,
            )
        )
        self.session.flush()

    def commands(self) -> list[dict[str, Any]]:
        rows = self.session.scalars(sa.select(EventOutbox).order_by(EventOutbox.id)).all()
        return [
            row.payload_json if isinstance(row.payload_json, dict) else json.loads(row.payload_json) for row in rows
        ]

    def ledger(self) -> list[NotificationDelivery]:
        return list(self.session.scalars(sa.select(NotificationDelivery).order_by(NotificationDelivery.id)).all())

    # -- personal ---------------------------------------------------------

    async def test_a_dm_is_one_outbox_command_and_one_ledger_row(self) -> None:
        """The happy path, and the shape the bot is asked for.

        ``allow_mentions=False`` is the security half: team names are user
        text, and ``@everyone`` inside one must ping nobody.
        """
        row = self.personal()
        self.link_discord()

        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))

        self.assertEqual(status, "sent")
        (command,) = self.commands()
        self.assertEqual(command["action"], "send_dm")
        self.assertEqual(command["discord_user_id"], int(DISCORD_ID))
        self.assertFalse(command["allow_mentions"])
        self.assertIn("Cup", command["card"]["text"])
        (entry,) = self.ledger()
        self.assertEqual(
            (entry.channel, entry.target, entry.dedupe_key), ("discord_dm", DISCORD_ID, f"notification:{row.id}")
        )
        self.assertEqual(entry.workspace_id, WORKSPACE)

    async def test_the_card_carries_the_organizers_current_branding(self) -> None:
        """Read at delivery, not from the snapshot: the workspace name above the
        heading, the tournament logo beside it, the workspace icon when there is none."""
        self.session.execute(
            sa.insert(models.Workspace.__table__).values(
                id=WORKSPACE, slug="anak", name="Anak Series", icon_url="https://cdn.example/ws.png"
            )
        )
        self.session.execute(
            sa.insert(models.Tournament.__table__).values(
                id=3, workspace_id=WORKSPACE, name="Cup", slug="cup", logo_url="https://cdn.example/cup.png"
            )
        )
        row = self.personal()
        self.link_discord()
        self.configure_workspace()

        await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))
        self.session.execute(sa.update(models.Tournament.__table__).values(logo_url=None))
        await self.service.deliver_broadcast(self.shim, self._broadcast())

        dm, post = (command["card"] for command in self.commands())
        self.assertTrue(dm["text"].startswith("-# Anak Series\n"))
        self.assertEqual(dm["thumbnail_url"], "https://cdn.example/cup.png")
        self.assertEqual(post["thumbnail_url"], "https://cdn.example/ws.png")

    async def test_a_switched_off_group_sends_nothing(self) -> None:
        """The opt-out has to bite before anything is written or queued."""
        row = self.personal()
        self.link_discord()
        self.session.add(NotificationPreference(auth_user_id=RECIPIENT, discord_dm={"tournament": False}))
        self.session.flush()

        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))

        self.assertEqual(status, "skipped_pref_off")
        self.assertEqual(self.commands(), [])
        self.assertEqual(self.ledger(), [])

    async def test_a_tournament_with_dms_muted_sends_nothing(self) -> None:
        """The organizer's switch bites at delivery, so a DM already queued stays unsent."""
        self.session.execute(
            sa.insert(models.Tournament.__table__).values(
                id=3, workspace_id=WORKSPACE, name="Cup", slug="cup", discord_dms_enabled=False
            )
        )
        row = self.personal()
        self.link_discord()

        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))

        self.assertEqual(status, "skipped_tournament_muted")
        self.assertEqual(self.commands(), [])
        self.assertEqual(self.ledger(), [])

    async def test_another_groups_switch_does_not_silence_this_one(self) -> None:
        """Groups are independent -- and an absent key is still the default."""
        row = self.personal(kind="encounter.scheduled")
        row.payload_json = {
            "encounter_id": 5,
            "tournament_id": 3,
            "tournament_name": "Cup",
            "home_team_name": "A",
            "away_team_name": "B",
            "scheduled_at": DEADLINE,
        }
        self.session.flush()
        self.link_discord()
        self.session.add(NotificationPreference(auth_user_id=RECIPIENT, discord_dm={"tournament": False}))
        self.session.flush()

        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))

        self.assertEqual(status, "sent")

    async def test_without_a_linked_discord_there_is_nobody_to_dm(self) -> None:
        row = self.personal()

        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))

        self.assertEqual(status, "skipped_no_discord")
        self.assertEqual(self.commands(), [])
        self.assertEqual(self.ledger(), [])

    async def test_a_redelivered_event_sends_once(self) -> None:
        """The outbox is at-least-once; the ledger is what makes delivery once."""
        row = self.personal()
        self.link_discord()
        event = NotificationCreatedEvent(notification_id=row.id)

        first = await self.service.deliver_personal(self.shim, event)
        second = await self.service.deliver_personal(self.shim, event)

        self.assertEqual((first, second), ("sent", "duplicate"))
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(len(self.commands()), 1)

    async def test_a_retired_notification_is_not_delivered(self) -> None:
        """An operator retiring a row before the drain must stop the DM."""
        row = self.personal(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        self.link_discord()

        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=row.id))

        self.assertEqual(status, "skipped_missing")
        self.assertEqual(self.commands(), [])

    async def test_a_vanished_notification_is_not_an_error(self) -> None:
        status = await self.service.deliver_personal(self.shim, NotificationCreatedEvent(notification_id=999))

        self.assertEqual(status, "skipped_missing")

    # -- broadcast --------------------------------------------------------

    def _broadcast(self, kind: str = "registration.opened") -> NotificationBroadcastEvent:
        return NotificationBroadcastEvent(
            workspace_id=WORKSPACE,
            kind=kind,
            payload={"tournament_id": 3, "tournament_name": "Cup"},
            dedupe_key="tournament:3",
        )

    async def test_a_workspace_channel_post_uses_the_workspace_locale(self) -> None:
        self.configure_workspace()

        status = await self.service.deliver_broadcast(self.shim, self._broadcast())

        self.assertEqual(status, "sent")
        (command,) = self.commands()
        self.assertEqual(command["action"], "post_message")
        self.assertEqual(command["channel_id"], CHANNEL_ID)
        self.assertFalse(command["allow_mentions"])
        self.assertIn("Registration for **Cup** is open.", command["card"]["text"])
        (entry,) = self.ledger()
        self.assertEqual(
            (entry.channel, entry.target, entry.dedupe_key),
            ("discord_channel", str(CHANNEL_ID), "registration.opened:tournament:3"),
        )

    async def test_a_workspace_without_a_config_posts_nothing(self) -> None:
        """No row, and a row with no channel picked, are the same answer."""
        no_row = await self.service.deliver_broadcast(self.shim, self._broadcast())
        self.configure_workspace(channel_id=None)
        no_channel = await self.service.deliver_broadcast(self.shim, self._broadcast())

        self.assertEqual((no_row, no_channel), ("skipped_no_config", "skipped_no_config"))
        self.assertEqual(self.commands(), [])

    async def test_a_kind_the_workspace_disabled_posts_nothing(self) -> None:
        """Scheduling a bracket round must not spam the channel by default."""
        self.configure_workspace(kinds=["registration.opened"])

        status = await self.service.deliver_broadcast(self.shim, self._broadcast(kind="check_in.opened"))

        self.assertEqual(status, "skipped_no_config")
        self.assertEqual(self.commands(), [])

    async def test_a_redelivered_broadcast_posts_once(self) -> None:
        self.configure_workspace()
        event = self._broadcast()

        first = await self.service.deliver_broadcast(self.shim, event)
        second = await self.service.deliver_broadcast(self.shim, event)

        self.assertEqual((first, second), ("sent", "duplicate"))
        self.assertEqual(len(self.commands()), 1)

    # -- the consumer ------------------------------------------------------

    async def test_the_consumer_routes_each_event_type_to_its_flow(self) -> None:
        """One queue carries both event types; the dispatch is the only thing
        that tells them apart, and a typo in either name is silent."""
        row = self.personal()
        self.link_discord()
        self.configure_workspace()

        handler = self._subscribe()
        await handler(NotificationCreatedEvent(notification_id=row.id).model_dump(mode="json"), _Message())
        await handler(self._broadcast().model_dump(mode="json"), _Message())

        actions = [command["action"] for command in self.commands()]
        self.assertEqual(actions, ["send_dm", "post_message"])

    async def test_the_consumer_ignores_an_event_it_has_no_flow_for(self) -> None:
        """The queue binds ``notification.*``; a future key must not crash the
        consumer into the DLQ before its handler exists."""
        handler = self._subscribe()

        await handler({"event_type": "notification.something_new"}, _Message())

        self.assertEqual(self.commands(), [])

    def _subscribe(self) -> Any:
        """The registered subscriber, with the worker's session factory swapped."""
        captured: dict[str, Any] = {}

        def subscriber(*_args: Any, **_kwargs: Any):
            def decorator(fn):
                captured["fn"] = fn
                return fn

            return decorator

        broker = MagicMock()
        broker.subscriber = subscriber
        consumer.register(broker, MagicMock())
        patcher = patch.object(db, "async_session_maker", _SessionMaker(self.shim))
        patcher.start()
        self.addCleanup(patcher.stop)
        return captured["fn"]
