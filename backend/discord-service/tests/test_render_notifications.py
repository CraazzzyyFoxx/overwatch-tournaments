"""Notification cards: what a template says, and how :func:`src.render.render` dresses a notification row.

Two halves. The template half needs no database at all -- ``render_discord`` is
a pure function over a payload snapshot -- and pins the three things a
template can silently get wrong: a kind with no translation, a team name that
italicises the rest of the line, and a link that points somewhere the inbox
does not. The row half runs against an in-memory SQLite engine behind a
sync-``Session`` shim, because what it adds is read from tables: the
workspace's locale, its name and icon, the tournament's logo.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import models  # noqa: E402
from shared.models.platform.notification import NotificationWorkspaceConfig  # noqa: E402
from shared.services.notifications import NOTIFICATION_KINDS  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src.render import Rendered, render  # noqa: E402
from src.render.notifications import DELIVERABLE_KINDS, TEMPLATES, deep_link_path, render_discord  # noqa: E402
from src.ui import EMOJI, SHORTCODE, emoji  # noqa: E402

install_postgres_type_shims()

SITE = "https://owt.example"
WORKSPACE = 7

DEADLINE = "2026-09-25T18:00:00+00:00"
# 2026-09-25T18:00:00Z as Discord reads it.
DEADLINE_UNIX = int(datetime(2026, 9, 25, 18, 0, tzinfo=UTC).timestamp())

#: Both teams known; the hour is a separate question (``exclude_none`` leaves
#: ``scheduled_at`` out entirely when there is none).
SCHEDULED = {
    "encounter_id": 5,
    "tournament_id": 3,
    "tournament_name": "Cup",
    "team_names": ["A", "B"],
}


class RenderDiscordTests(TestCase):
    """The templates themselves -- no session, no broker."""

    def test_every_deliverable_kind_is_translated_in_both_locales(self) -> None:
        """A kind without a template is a notification that silently never sends.

        ``announcement.published`` is the one exception: operator text already
        carries its own copy and never leaves the app.
        """
        deliverable = set(NOTIFICATION_KINDS) - {"announcement.published"}

        for locale in ("ru", "en"):
            self.assertEqual(set(TEMPLATES[locale]), deliverable, locale)

    def test_encounter_cards_name_every_seat_in_slot_order(self) -> None:
        """The payload's ``team_names`` is the list of every participation; a card
        reads it whole, however many seats the encounter has."""
        fixture = {**SCHEDULED, "team_names": ["A", "B", "C"], "scheduled_at": DEADLINE}

        scheduled = render_discord("encounter.scheduled", fixture, locale="en", site_url=SITE)
        self.assertIn("**A** vs **B** vs **C** in **Cup**.", scheduled.text)
        ru = render_discord("encounter.scheduled", fixture, locale="ru", site_url=SITE)
        self.assertIn("**A** — **B** — **C** на **Cup**.", ru.text)

        dispute = render_discord("encounter.dispute_review", {**fixture, "position": 0}, locale="en", site_url=SITE)
        self.assertIn("**A**, **B** and **C** reported different scores.", dispute.text)
        pair = render_discord(
            "encounter.dispute_review",
            {**fixture, "team_names": ["A*", "B"], "position": 0},
            locale="ru",
            site_url=SITE,
        )
        # Names are user text: escaped, never able to open markdown of their own.
        self.assertIn("Капитаны **A\\*** и **B** разошлись в счёте.", pair.text)

    def test_every_card_names_emoji_the_bot_knows(self) -> None:
        """A heading and every button name an emoji out of ``EMOJI``.

        discord-service swaps a ``:owt_<name>:`` shortcode for the uploaded
        application emoji; a name that is not in the set reaches the reader as
        that literal text, inside a message nobody can edit afterwards. The
        words have to stand on their own too -- a button needs a label even when
        the emoji resolves, and a heading stripped of its badge is still the
        sentence the inbox shows.
        """
        payload = {
            "tournament_id": 3,
            "tournament_name": "Cup",
            "team_id": 1,
            "team_name": "T",
            "invite_id": 42,
            "responder_name": "R",
            "answer": "accepted",
            "slot_code": "tank",
            "is_substitute": False,
            "encounter_id": 5,
            "position": 1,
            "reason": "no show",
            "closes_at": DEADLINE,
            "scheduled_at": DEADLINE,
            "team_names": ["A", "B"],
            "custom_game_id": 12,
            "mix_name": "Friday",
            "lobby": "B",
        }

        for locale in ("ru", "en"):
            for kind in sorted(DELIVERABLE_KINDS):
                # ``personal`` is the widest card: every button this kind has.
                card = render_discord(kind, payload, locale=locale, site_url=SITE, personal=True)
                badge, *rest = SHORTCODE.findall(card.text)
                heading = card.text.splitlines()[0]

                self.assertEqual(rest, [], (kind, locale))
                self.assertIn(badge, EMOJI, (kind, locale))
                self.assertTrue(heading.startswith(f"### {emoji(badge)} "), (kind, locale))
                self.assertTrue(heading.removeprefix(f"### {emoji(badge)} ").strip(), (kind, locale))
                for button in [*card.answers, *(b for row in card.rows for b in row)]:
                    self.assertIn(button.emoji, EMOJI, (kind, locale, button.label))
                    self.assertTrue(button.label.strip(), (kind, locale, button.emoji))

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
                "team_names": ["A", "B"],
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

    def test_an_announcement_names_the_registration_node_when_it_has_one(self) -> None:
        """Several intakes can run in one tournament ("Day 3"); the card says which one opened."""
        payload = {"tournament_id": 3, "tournament_name": "Cup"}

        for kind in ("registration.opened", "check_in.opened"):
            named = render_discord(kind, {**payload, "node_name": "Day 3"}, locale="en", site_url=SITE)
            self.assertIn("**Intake:** Day 3", named.details, kind)
            self.assertIsNone(render_discord(kind, payload, locale="en", site_url=SITE).details, kind)

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
            "encounter.dispute_review": "/tournaments/3/pregame/5",
            "encounter.scheduled": "/tournaments/3/pregame/5",
            "registration.opened": "/tournaments/3",
            "check_in.opened": "/tournaments/3",
            "team_invite.answered": None,
        }
        payload = {"tournament_id": 3, "encounter_id": 5}

        for kind, expected in cases.items():
            self.assertEqual(deep_link_path(kind, payload), expected, kind)

    def test_a_mix_captains_dm_links_the_lobby_room(self) -> None:
        """R3-3: one sentence for the captain and one button, the lobby's own room -- the inbox's href."""
        payload = {"custom_game_id": 12, "mix_name": "Friday *mix*", "lobby": "B"}

        ban_ru = render_discord("mix.ban_room_opened", payload, locale="ru", site_url=SITE, personal=True)
        draft_en = render_discord("mix.draft_started", payload, locale="en", site_url=SITE)

        self.assertIn("Вы капитан в лобби B микса **Friday \\*mix\\***: открылась комната банов героев.", ban_ru.text)
        self.assertIn(
            "You captain lobby B of **Friday \\*mix\\***: the draft has started — pick on your turn.", draft_en.text
        )
        self.assertEqual(
            [("Комната лобби", f"{SITE}/balancer/mix/12/lobby/B")],
            [(button.label, button.url) for button in ban_ru.rows[-1] if button.type == "link"],
        )
        self.assertEqual("/balancer/mix/12/lobby/B", deep_link_path("mix.draft_started", payload))
        for broken in ({"custom_game_id": 12, "lobby": "AB"}, {"lobby": "B"}, {"custom_game_id": 12}):
            self.assertIsNone(deep_link_path("mix.ban_room_opened", broken), broken)

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
            "check_in.opened",
            {"tournament_id": 3, "tournament_name": "Cup", "registration_node_id": 7},
            locale="ru",
            site_url=SITE,
        )
        no_node = render_discord(
            "check_in.opened", {"tournament_id": 3, "tournament_name": "Cup"}, locale="ru", site_url=SITE
        )
        opened = render_discord(
            "registration.opened", {"tournament_id": 3, "tournament_name": "Cup"}, locale="ru", site_url=SITE
        )

        self.assertEqual(
            [(b.action, b.target) for b in invite.answers], [("invite.accept", "42"), ("invite.decline", "42")]
        )
        # The entry routes need the registration node too: ``<tournament>-<node>``.
        self.assertEqual(
            [(b.action, b.target) for b in check_in.answers], [("check_in", "3-7"), ("registration.view", "3-7")]
        )
        # A button that cannot name its node would only fail on click.
        self.assertEqual(no_node.answers, [])
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

    def test_a_match_with_no_time_yet_is_still_worth_a_card(self) -> None:
        """Both teams are known the moment the bracket advances; the hour often
        is not. The card announces the match, and drops the empty time line."""
        tbd = render_discord("encounter.scheduled", SCHEDULED, locale="ru", site_url=SITE)
        timed = render_discord(
            "encounter.scheduled", {**SCHEDULED, "scheduled_at": DEADLINE}, locale="ru", site_url=SITE
        )

        self.assertIn(f"### {emoji('vs')} Следующий матч", tbd.text)
        self.assertIsNone(tbd.details)
        self.assertIn(f"### {emoji('vs')} Матч назначен", timed.text)
        self.assertIn(f"<t:{DEADLINE_UNIX}:F>", timed.details)

    def test_the_match_card_leads_with_what_its_reader_can_do(self) -> None:
        """A DM's reader plays the match: the room comes first, named after what
        waits there. A channel post is read by everyone, so it leads with the
        public page and only shows the room when there is a pick-ban to enter."""
        pick_ban = {**SCHEDULED, "pick_ban": True}
        room, match = f"{SITE}/tournaments/3/pregame/5", f"{SITE}/encounters/5"

        dm = render_discord("encounter.scheduled", SCHEDULED, locale="ru", site_url=SITE, personal=True)
        dm_pick_ban = render_discord("encounter.scheduled", pick_ban, locale="en", site_url=SITE, personal=True)
        post = render_discord("encounter.scheduled", SCHEDULED, locale="ru", site_url=SITE)
        post_pick_ban = render_discord("encounter.scheduled", pick_ban, locale="en", site_url=SITE)

        self.assertEqual(
            [(b.label, getattr(b, "url", b.type)) for b in dm.rows[-1]],
            [("Комната матча", room), ("Матч", match), ("Уведомления", "action")],
        )
        self.assertEqual(
            [(b.label, getattr(b, "url", b.type)) for b in dm_pick_ban.rows[-1]],
            [("Pick-ban", room), ("Match", match), ("Notifications", "action")],
        )
        self.assertEqual([(b.label, b.url) for b in post.rows[-1]], [("Матч", match)])
        self.assertEqual([(b.label, b.url) for b in post_pick_ban.rows[-1]], [("Match", match), ("Pick-ban", room)])

    def test_the_match_card_carries_its_own_opengraph_image(self) -> None:
        """``?v=`` busts Discord's per-URL media cache: the same payload has to
        keep the same URL, a new opponent or a new time a different one."""
        card = render_discord("encounter.scheduled", SCHEDULED, locale="ru", site_url=f"{SITE}/")
        again = render_discord("encounter.scheduled", dict(reversed(SCHEDULED.items())), locale="en", site_url=SITE)
        timed = render_discord(
            "encounter.scheduled", {**SCHEDULED, "scheduled_at": DEADLINE}, locale="ru", site_url=SITE
        )
        other = render_discord(
            "check_in.opened", {"tournament_id": 3, "tournament_name": "Cup"}, locale="ru", site_url=SITE
        )

        self.assertRegex(card.image_url, rf"^{SITE}/encounters/5/og\?v=[0-9a-f]{{12}}$")
        self.assertEqual(card.image_url, again.image_url)
        self.assertNotEqual(card.image_url, timed.image_url)
        # Only an encounter has a picture of its own.
        self.assertIsNone(other.image_url)


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` -- no async SQLite driver."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)


class RenderNotificationRowTests(IsolatedAsyncioTestCase):
    """The row half: locale and branding are read when the card is rendered, not snapshotted."""

    def setUp(self) -> None:
        engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        tables = (models.Workspace.__table__, models.Tournament.__table__, NotificationWorkspaceConfig.__table__)
        with engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)
        self.session = Session(engine)
        self.addCleanup(engine.dispose)
        self.addCleanup(self.session.close)
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

    async def render(self, *, channel: str = "discord_dm", payload: Any = None) -> Any:
        row = models.DiscordMessage(
            id=1,
            channel=channel,
            target="4242",
            subject="notification:1",
            slot="dm" if channel == "discord_dm" else "channel",
            kind="check_in.opened",
            status="pending",
            workspace_id=WORKSPACE,
            payload_json={"tournament_id": 3, "tournament_name": "Cup"} if payload is None else payload,
        )
        return await render(_AsyncSessionShim(self.session), row, broker=None)

    async def test_a_dm_wears_the_organizers_current_branding_and_its_way_out(self) -> None:
        """The workspace name above the heading, the tournament logo beside it, and
        -- for its one reader -- the button that switches DMs off. Nothing pings."""
        rendered = await self.render()

        self.assertIsInstance(rendered, Rendered)
        self.assertTrue(rendered.card.text.startswith("-# Anak Series\n"))
        self.assertEqual(rendered.card.thumbnail_url, "https://cdn.example/cup.png")
        self.assertEqual(rendered.card.rows[-1][-1].action, "notifications.menu")
        self.assertIsNone(rendered.file)
        self.assertEqual(rendered.allowed_mentions.to_dict(), {"parse": []})

    async def test_a_channel_post_falls_back_to_the_workspace_icon_and_has_no_single_reader(self) -> None:
        self.session.execute(sa.update(models.Tournament.__table__).values(logo_url=None))

        rendered = await self.render(channel="discord_channel")

        self.assertEqual(rendered.card.thumbnail_url, "https://cdn.example/ws.png")
        self.assertNotIn("notifications.menu", [getattr(b, "action", None) for b in rendered.card.rows[-1]])

    async def test_the_card_speaks_the_workspace_locale_and_russian_without_one(self) -> None:
        russian = await self.render()
        self.session.add(NotificationWorkspaceConfig(workspace_id=WORKSPACE, locale="en", broadcast_kinds=[]))
        self.session.flush()
        english = await self.render()

        self.assertIn("Чек-ин открыт", russian.card.text)
        self.assertIn("Check-in opened", english.card.text)

    async def test_a_payload_that_fills_no_card_is_nothing_to_show(self) -> None:
        """A publisher bug fails the same way on every retry: not a requeue loop."""
        self.assertIsNone(await self.render(payload={}))
        self.assertIsNone(await self.render(payload=[]))
