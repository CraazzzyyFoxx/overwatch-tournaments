"""Contract guards on ``rpc.stream.tournament_streams``.

Seven properties, each of which fails silently in production if it drifts:

1. **The visibility gate runs first.** The gateway caches this response with
   ``respcache.TTLOnly`` — no viewer in the cache key — so a hidden tournament
   must be rejected before a single stream row or Redis key is touched, and it
   must answer 404 rather than 403 so existence stays undisclosed.
2. **``participants`` is "who is on air", nothing else.** A channel the poller
   stamped ``source="official"`` belongs to the official block even when it has a
   ``player_id``, or the same stream renders twice.
3. **``live=None`` is not ``live=False``.** A YouTube link is never polled, so
   claiming it is offline invents a fact. Same for a Twitch URL that is not a
   channel page: there is no login to ask Helix about.
4. **Player enrichment is one query**, team included. A tournament page can carry
   dozens of live channels, and this read is public.
5. **The team pick is a function of the data, not of row order.** A participant can
   have two roster rows in one tournament (a substitute covering their slot), so an
   unranked pick would move them between teams from tick to tick.
6. **A participant who vetoed being broadcast is not published**, even though the
   poller left them in the Redis hash on the previous tick, and even when they are
   verified. And an entry whose ``player_id`` resolves to nothing is withheld for the
   same reason: consent we cannot read is consent we do not have.
7. **The roster gate flips exactly once, on the data.** Before the tournament has
   rosters every approved registrant on air is a participant; after it, a
   streamer with no team is not. Keyed on an EXISTS over ``tournament.player``,
   not on ``status``, so a hand-advanced tournament that never drafted still
   shows everyone.

No database and no Redis: the gate and the batched lookup are exercised against a
fake session that answers the two statement shapes this path issues.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stream-service"))


from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.tournament.link import TournamentLink  # noqa: E402
from shared.models.tournament.tournament import Tournament  # noqa: E402
from src.rpc import reads  # noqa: E402


def _snapshot(
    channel: str,
    *,
    source: str,
    player_id: int | None = None,
    viewer_count: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """One poller snapshot. Note the absent ``live`` key: the field's existence in
    the hash IS the liveness signal (``src/services/state.py``)."""
    return {
        "platform": "twitch",
        "channel": channel,
        "user_id": "1234",
        "url": f"https://twitch.tv/{channel}",
        "title": title,
        "game_name": "Overwatch 2",
        "viewer_count": viewer_count,
        "thumbnail_url": f"https://static-cdn.jtvnw.net/previews/{channel}-440x248.jpg",
        "started_at": "2026-08-16T12:00:00Z",
        "player_id": player_id,
        "source": source,
    }


class _FakeRedis:
    """Serves one tournament's live hash and records that it was asked."""

    def __init__(self, snapshots: dict[str, dict[str, Any]]) -> None:
        self._snapshots = snapshots
        self.hgetall_keys: list[str] = []

    async def hgetall(self, key: str) -> dict[str, str]:
        self.hgetall_keys.append(key)
        return {field: json.dumps(snapshot) for field, snapshot in self._snapshots.items()}


class _FakeSession:
    """Answers the two statement shapes this read issues.

    ``scalar`` serves the visibility gate's tournament load; ``execute`` serves the
    batched player lookup. ``executed`` is the N+1 tripwire.
    """

    def __init__(self, tournament: Tournament | None, player_rows: list[Any] | None = None) -> None:
        self._tournament = tournament
        self._player_rows = player_rows or []
        self.executed: list[Any] = []

    async def scalar(self, statement: Any) -> Any:
        # ``assert_tournament_viewable`` now joinedloads ``Tournament.workspace``
        # for the workspace-hidden cascade; this fake never runs a real join, so
        # stub a non-hidden workspace onto the transient tournament directly.
        if self._tournament is not None:
            self._tournament.workspace = SimpleNamespace(is_hidden=False)
        return self._tournament

    async def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return SimpleNamespace(all=lambda: list(self._player_rows))


def _link(url: str, label: str | None = None, sort_order: int = 0) -> TournamentLink:
    return TournamentLink(tournament_id=1, kind="stream", url=url, label=label, sort_order=sort_order, is_active=True)


def _player_row(
    player_id: int,
    name: str,
    *,
    roster_id: int | None = None,
    is_substitution: bool = False,
    team: tuple[int, str] | None = None,
    stream_visible: bool = True,
    rosters_formed: bool | None = None,
) -> SimpleNamespace:
    """One row of the batched player+roster join.

    ``team=None`` is the pre-draft state, and the shape the LEFT JOINs really
    produce: no roster row matched, so every roster column comes back NULL.

    ``stream_visible=False`` is the owner's veto on being broadcast — the row still
    comes back from the DB, and the read is what must refuse to publish it.

    ``rosters_formed`` is tournament-wide, not per-row, so it defaults to "this
    row has a team" — the shape the real query produces whenever the caller is
    not deliberately mixing drafted and undrafted players. Pass it explicitly to
    build the mixed tournament: a drafted field with one teamless streamer in it.
    """
    return SimpleNamespace(
        id=player_id,
        name=name,
        avatar_url=None,
        stream_visible=stream_visible,
        roster_id=roster_id,
        is_substitution=is_substitution,
        team_id=None if team is None else team[0],
        team_name=None if team is None else team[1],
        rosters_formed=(team is not None) if rosters_formed is None else rosters_formed,
    )


class HiddenTournamentGateTests(IsolatedAsyncioTestCase):
    async def test_hidden_tournament_404s_an_anonymous_viewer_before_reading_anything(self) -> None:
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=True))
        redis = _FakeRedis({"twitch:caster": _snapshot("caster", source="official")})
        links = AsyncMock(return_value=[_link("https://twitch.tv/caster")])

        with patch.object(reads._reader._targets, "official_stream_links", links):
            with self.assertRaises(HTTPException) as ctx:
                await reads.tournament_streams(session, redis, {"tournament_id": "1"})

        # 404, not 403: a hidden tournament and a missing one are indistinguishable.
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Tournament not found")
        # And nothing was read. An empty response would be just as wrong as a 403 --
        # it would mean the gate ran after the cacheable read it is supposed to guard.
        self.assertEqual(redis.hgetall_keys, [])
        links.assert_not_awaited()
        self.assertEqual(session.executed, [])

    async def test_visible_tournament_is_served(self) -> None:
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False))
        redis = _FakeRedis({})

        with patch.object(reads._reader._targets, "official_stream_links", AsyncMock(return_value=[])):
            result = await reads.tournament_streams(session, redis, {"tournament_id": "1"})

        self.assertEqual(result.official, [])
        self.assertEqual(result.participants, [])
        self.assertEqual(redis.hgetall_keys, ["stream:live:1"])

    async def test_missing_tournament_id_is_unprocessable(self) -> None:
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False))
        with self.assertRaises(HTTPException) as ctx:
            await reads.tournament_streams(session, _FakeRedis({}), {})
        self.assertEqual(ctx.exception.status_code, 422)


class ParticipantsTests(IsolatedAsyncioTestCase):
    """``participants`` = the live set, minus the official broadcast, with players."""

    def setUp(self) -> None:
        self.snapshots = {
            # The official broadcast. It carries a player_id (the caster happens to
            # be a registered participant) but source wins: official block only.
            "twitch:caster": _snapshot("caster", source="official", player_id=10, viewer_count=900),
            "twitch:alice": _snapshot("alice", source="self_declared", player_id=11, viewer_count=40),
            "twitch:bob": _snapshot("bob", source="verified", player_id=12, viewer_count=120),
            # Live, but no player resolved -- nothing to attribute it to, so it is
            # neither an official link nor a participant entry.
            "twitch:stranger": _snapshot("stranger", source="verified", player_id=None),
        }
        self.session = _FakeSession(
            Tournament(id=1, workspace_id=5, is_hidden=False),
            [_player_row(11, "Alice"), _player_row(12, "Bob")],
        )
        self.redis = _FakeRedis(self.snapshots)

    async def _run(self) -> Any:
        with patch.object(
            reads._reader._targets,
            "official_stream_links",
            AsyncMock(return_value=[_link("https://twitch.tv/caster")]),
        ):
            return await reads.tournament_streams(self.session, self.redis, {"tournament_id": "1"})

    async def test_participants_are_the_live_player_channels_only(self) -> None:
        result = await self._run()

        # Biggest audience first, so a TTL-cached response is stable across calls.
        self.assertEqual([e.channel for e in result.participants], ["bob", "alice"])
        self.assertTrue(all(e.live is True for e in result.participants))

    async def test_official_channel_is_not_repeated_as_a_participant(self) -> None:
        result = await self._run()

        self.assertEqual([e.channel for e in result.official], ["caster"])
        self.assertNotIn("caster", [e.channel for e in result.participants])
        # The official slot is the organizer's, not the caster's, even though the
        # snapshot resolved a player behind it.
        self.assertIsNone(result.official[0].player)

    async def test_players_are_enriched_in_a_single_query(self) -> None:
        result = await self._run()

        by_channel = {e.channel: e for e in result.participants}
        self.assertEqual(by_channel["alice"].player.name, "Alice")  # type: ignore[union-attr]
        self.assertEqual(by_channel["bob"].player.id, 12)  # type: ignore[union-attr]
        # Two players, one round trip. Per-entry lookups would make this len 2.
        self.assertEqual(len(self.session.executed), 1)

    async def test_live_metadata_rides_along(self) -> None:
        result = await self._run()

        bob = next(e for e in result.participants if e.channel == "bob")
        self.assertEqual(bob.viewer_count, 120)
        self.assertEqual(bob.game_name, "Overwatch 2")
        self.assertIsNotNone(bob.started_at)
        self.assertNotIn("{width}", bob.thumbnail_url or "")


class OfficialLinkLivenessTests(IsolatedAsyncioTestCase):
    """The tri-state. ``None`` means "nobody checked", and must not become False."""

    async def _official(self, links: list[TournamentLink], snapshots: dict[str, dict[str, Any]]) -> Any:
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False))
        with patch.object(reads._reader._targets, "official_stream_links", AsyncMock(return_value=links)):
            result = await reads.tournament_streams(session, _FakeRedis(snapshots), {"tournament_id": "1"})
        return result.official

    async def test_youtube_link_is_unknown_not_offline(self) -> None:
        official = await self._official([_link("https://www.youtube.com/@aqt", label="AQT")], {})

        self.assertEqual(official[0].platform, "youtube")
        # The load-bearing assertion of this whole feature's frontend: `is None`,
        # not `is False`. False would render a grey "offline" badge on a channel
        # the poller never looks at.
        self.assertIsNone(official[0].live)
        self.assertEqual(official[0].channel, "AQT")

    async def test_twitch_non_channel_url_is_unknown(self) -> None:
        official = await self._official([_link("https://twitch.tv/videos/123456")], {})

        self.assertEqual(official[0].platform, "twitch")
        self.assertIsNone(official[0].live)

    async def test_twitch_channel_absent_from_the_live_set_is_offline(self) -> None:
        official = await self._official([_link("https://twitch.tv/caster")], {})

        # Here False is correct and None would be wrong: this channel IS polled,
        # and Helix omits offline channels from GET /streams.
        self.assertIs(official[0].live, False)
        self.assertEqual(official[0].channel, "caster")

    async def test_offline_official_link_is_still_returned(self) -> None:
        official = await self._official([_link("https://twitch.tv/caster")], {})

        self.assertEqual([e.url for e in official], ["https://twitch.tv/caster"])

    async def test_live_official_link_keeps_the_organizers_url(self) -> None:
        official = await self._official(
            [_link("https://twitch.tv/caster?lang=ru")],
            {"twitch:caster": _snapshot("caster", source="official", title="Grand Final")},
        )

        self.assertIs(official[0].live, True)
        self.assertEqual(official[0].url, "https://twitch.tv/caster?lang=ru")
        self.assertEqual(official[0].title, "Grand Final")

    async def test_links_keep_the_services_ordering(self) -> None:
        official = await self._official(
            [_link("https://twitch.tv/main", sort_order=0), _link("https://twitch.tv/second", sort_order=1)],
            {},
        )

        self.assertEqual([e.channel for e in official], ["main", "second"])


class NonTwitchPlatformStampTests(IsolatedAsyncioTestCase):
    """The read stamps whatever ``targets.platform_from_url`` says, and only Twitch
    ever gets a boolean. The host rules themselves are tested where they live
    (``tests/test_target_queries.py``) — duplicating them here would give two
    places to update when Twitch adds a host."""

    async def test_unknown_host_is_other_and_unknown(self) -> None:
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False))
        with patch.object(
            reads._reader._targets,
            "official_stream_links",
            AsyncMock(return_value=[_link("https://kick.com/aqt", label="Kick")]),
        ):
            result = await reads.tournament_streams(session, _FakeRedis({}), {"tournament_id": "1"})

        self.assertEqual(result.official[0].platform, "other")
        self.assertIsNone(result.official[0].live)
        self.assertEqual(result.official[0].channel, "Kick")

    async def test_unlabelled_link_falls_back_to_the_host(self) -> None:
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False))
        with patch.object(
            reads._reader._targets,
            "official_stream_links",
            AsyncMock(return_value=[_link("https://www.youtube.com/@aqt")]),
        ):
            result = await reads.tournament_streams(session, _FakeRedis({}), {"tournament_id": "1"})

        self.assertEqual(result.official[0].channel, "youtube.com")


class ParticipantTeamTests(IsolatedAsyncioTestCase):
    """The team behind a participant entry.

    The interesting case is not "a team is returned" but WHICH roster row answers
    when a participant has more than one, because every candidate row carries a
    plausible team and the wrong pick looks like a working feature.
    """

    async def _run(
        self,
        rows: list[Any],
        *,
        channels: dict[str, int] | None = None,
    ) -> tuple[Any, _FakeSession]:
        channels = channels or {"alice": 11}
        snapshots = {
            f"twitch:{channel}": _snapshot(channel, source="self_declared", player_id=player_id)
            for channel, player_id in channels.items()
        }
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False), rows)
        with patch.object(reads._reader._targets, "official_stream_links", AsyncMock(return_value=[])):
            result = await reads.tournament_streams(session, _FakeRedis(snapshots), {"tournament_id": "1"})
        return result, session

    async def test_one_roster_row_gives_the_participant_their_team(self) -> None:
        result, _ = await self._run([_player_row(11, "Alice", roster_id=5, team=(3, "Team Rocket"))])

        team = result.participants[0].player.team  # type: ignore[union-attr]
        self.assertEqual((team.id, team.name), (3, "Team Rocket"))

    async def test_the_starting_row_wins_over_the_substitution_row(self) -> None:
        # The substitute deliberately has the LOWER roster id: a pick that only
        # ordered by id would answer "Bench" here. Both row orders are asserted --
        # a naive first-row-wins and a naive last-row-wins each fail one of them,
        # which is the whole point of ranking the rows.
        sub = _player_row(11, "Alice", roster_id=1, is_substitution=True, team=(9, "Bench"))
        starter = _player_row(11, "Alice", roster_id=2, team=(3, "Team Rocket"))

        for rows in ([sub, starter], [starter, sub]):
            with self.subTest(order=[row.roster_id for row in rows]):
                result, _ = await self._run(rows)
                self.assertEqual(result.participants[0].player.team.name, "Team Rocket")  # type: ignore[union-attr]

    async def test_the_lowest_roster_id_breaks_a_tie_between_starting_rows(self) -> None:
        result, _ = await self._run(
            [
                _player_row(11, "Alice", roster_id=7, team=(9, "Later")),
                _player_row(11, "Alice", roster_id=3, team=(3, "Earlier")),
            ]
        )

        self.assertEqual(result.participants[0].player.team.name, "Earlier")  # type: ignore[union-attr]

    async def test_a_row_that_found_a_roster_beats_one_that_did_not(self) -> None:
        # A user who belongs to several workspaces matches several
        # ``workspace_member`` rows, and only one of them can own a roster row in
        # this tournament; the rest arrive with the roster columns NULL.
        matched = _player_row(11, "Alice", roster_id=5, team=(3, "Team Rocket"))
        unmatched = _player_row(11, "Alice")

        for rows in ([unmatched, matched], [matched, unmatched]):
            with self.subTest(first="unmatched" if rows[0] is unmatched else "matched"):
                result, _ = await self._run(rows)
                self.assertEqual(result.participants[0].player.team.name, "Team Rocket")  # type: ignore[union-attr]

    async def test_participant_without_a_roster_is_served_with_a_null_team(self) -> None:
        result, _ = await self._run([_player_row(11, "Alice")])

        player = result.participants[0].player
        self.assertEqual(player.name, "Alice")  # type: ignore[union-attr]
        # No roster is the normal state before the draft, so the entry is served
        # with ``team: null`` rather than failing validation on a missing field.
        self.assertIsNone(player.team)  # type: ignore[union-attr]
        self.assertIn("team", player.model_dump())  # type: ignore[union-attr]

    async def test_official_broadcast_carries_no_player_and_therefore_no_team(self) -> None:
        session = _FakeSession(
            Tournament(id=1, workspace_id=5, is_hidden=False),
            [_player_row(11, "Alice", roster_id=5, team=(3, "Team Rocket"))],
        )
        snapshots = {"twitch:caster": _snapshot("caster", source="official", player_id=11)}

        with patch.object(
            reads._reader._targets,
            "official_stream_links",
            AsyncMock(return_value=[_link("https://twitch.tv/caster")]),
        ):
            result = await reads.tournament_streams(session, _FakeRedis(snapshots), {"tournament_id": "1"})

        self.assertIsNone(result.official[0].player)
        self.assertEqual(result.participants, [])
        # Nothing to enrich, so the roster query never runs at all.
        self.assertEqual(session.executed, [])

    async def test_team_enrichment_does_not_add_a_query_per_participant(self) -> None:
        channels = {f"p{index}": 20 + index for index in range(6)}
        rows = [
            _player_row(20 + index, f"P{index}", roster_id=100 + index, team=(3 + index, f"Team {index}"))
            for index in range(6)
        ]

        result, session = await self._run(rows, channels=channels)

        self.assertEqual(len(result.participants), 6)
        self.assertEqual({entry.player.team.name for entry in result.participants}, {f"Team {i}" for i in range(6)})  # type: ignore[union-attr]
        # Six participants, one round trip -- the team join rides along instead of
        # adding a statement.
        self.assertEqual(len(session.executed), 1)


class RosterGateTests(IsolatedAsyncioTestCase):
    """Who counts as a participant, before and after the teams exist.

    The block answers "who is on air in this tournament", and what that means
    changes exactly once: while there are no rosters, every approved registrant
    on air belongs on the page (streaming during ``check_in`` is the point);
    once the tournament has rosters, a streamer with no team is someone the
    draft left out and is not part of the tournament being played.

    The switch is the DATA, not the status: ``rosters_formed`` is an EXISTS over
    ``tournament.player`` for this tournament, so a tournament whose organizer
    advanced the status by hand without drafting still shows everyone.
    """

    async def _run(self, rows: list[Any], channels: dict[str, int]) -> tuple[Any, _FakeSession]:
        snapshots = {
            f"twitch:{channel}": _snapshot(channel, source="self_declared", player_id=player_id)
            for channel, player_id in channels.items()
        }
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False), rows)
        with patch.object(reads._reader._targets, "official_stream_links", AsyncMock(return_value=[])):
            result = await reads.tournament_streams(session, _FakeRedis(snapshots), {"tournament_id": "1"})
        return result, session

    async def test_before_the_draft_a_teamless_streamer_is_published(self) -> None:
        result, _ = await self._run(
            [_player_row(11, "Alice", rosters_formed=False)],
            {"alice": 11},
        )

        self.assertEqual([entry.channel for entry in result.participants], ["alice"])
        self.assertIsNone(result.participants[0].player.team)  # type: ignore[union-attr]

    async def test_once_rosters_exist_a_teamless_streamer_is_withheld(self) -> None:
        # Same row as above but for the tournament-wide flag: the ONLY difference
        # is that somebody, somewhere in this tournament, now has a roster row.
        result, _ = await self._run(
            [_player_row(11, "Alice", rosters_formed=True)],
            {"alice": 11},
        )

        self.assertEqual(result.participants, [])

    async def test_the_gate_keeps_the_drafted_players_of_a_mixed_field(self) -> None:
        # The real post-draft shape: Bob made a team, Alice did not, and both are
        # live. A blanket gate would empty the block; no gate at all would keep
        # Alice on a page about the tournament she is not playing in.
        result, _ = await self._run(
            [
                _player_row(11, "Alice", rosters_formed=True),
                _player_row(12, "Bob", roster_id=5, team=(3, "Team Rocket")),
            ],
            {"alice": 11, "bob": 12},
        )

        self.assertEqual([entry.channel for entry in result.participants], ["bob"])
        self.assertEqual(result.participants[0].player.team.name, "Team Rocket")  # type: ignore[union-attr]

    async def test_a_substitute_is_a_roster_row_and_stays_on_the_page(self) -> None:
        # ``Player.team_id`` is NOT NULL, so a substitute carries a team like any
        # other roster row -- the gate must not read "bench" as "not drafted".
        result, _ = await self._run(
            [_player_row(11, "Alice", roster_id=1, is_substitution=True, team=(9, "Bench"))],
            {"alice": 11},
        )

        self.assertEqual([entry.channel for entry in result.participants], ["alice"])
        self.assertEqual(result.participants[0].player.team.name, "Bench")  # type: ignore[union-attr]

    async def test_the_gate_rides_the_existing_query(self) -> None:
        channels = {f"p{index}": 20 + index for index in range(4)}
        rows = [
            _player_row(20 + index, f"P{index}", roster_id=100 + index, team=(3 + index, f"Team {index}"))
            for index in range(4)
        ]

        result, session = await self._run(rows, channels)

        self.assertEqual(len(result.participants), 4)
        # ``rosters_formed`` is a column of the batched join, so asking whether
        # the tournament is drafted must not cost a second statement.
        self.assertEqual(len(session.executed), 1)


class StreamVetoDisplayGateTests(IsolatedAsyncioTestCase):
    """The display half of ``players.user.stream_visible``.

    The collection gate in ``services/targets.py`` keeps a vetoed channel out of the
    NEXT poll, which leaves a 30-60s window where the hash still holds the previous
    tick's entry. That window is the whole reason this gate exists, so these tests
    always start from "the entry is already in Redis".
    """

    async def _run(
        self,
        rows: list[Any],
        *,
        channels: dict[str, tuple[int, str]],
        links: list[TournamentLink] | None = None,
    ) -> tuple[Any, _FakeSession]:
        snapshots = {
            f"twitch:{channel}": _snapshot(channel, source=source, player_id=player_id)
            for channel, (player_id, source) in channels.items()
        }
        session = _FakeSession(Tournament(id=1, workspace_id=5, is_hidden=False), rows)
        with patch.object(reads._reader._targets, "official_stream_links", AsyncMock(return_value=links or [])):
            result = await reads.tournament_streams(session, _FakeRedis(snapshots), {"tournament_id": "1"})
        return result, session

    async def test_a_vetoed_self_declared_participant_is_withheld(self) -> None:
        result, _ = await self._run(
            [_player_row(11, "Alice", stream_visible=False)],
            channels={"alice": (11, "self_declared")},
        )

        self.assertEqual(result.participants, [])

    async def test_a_vetoed_verified_participant_is_withheld(self) -> None:
        # The path that had no off switch at all before this column: a verified,
        # publicly visible Twitch account was consent enough.
        result, _ = await self._run(
            [_player_row(12, "Bob", roster_id=5, team=(3, "Team Rocket"), stream_visible=False)],
            channels={"bob": (12, "verified")},
        )

        self.assertEqual(result.participants, [])

    async def test_the_veto_removes_only_the_player_who_set_it(self) -> None:
        result, _ = await self._run(
            [
                _player_row(11, "Alice", stream_visible=False),
                _player_row(12, "Bob", roster_id=5, team=(3, "Team Rocket")),
            ],
            channels={"alice": (11, "self_declared"), "bob": (12, "verified")},
        )

        self.assertEqual([entry.channel for entry in result.participants], ["bob"])
        self.assertEqual(result.participants[0].player.name, "Bob")  # type: ignore[union-attr]

    async def test_both_consent_paths_still_publish_without_a_veto(self) -> None:
        """Regression guard: the gate must not become a blanket "hide participants".

        Both players are drafted, so the roster gate (``RosterGateTests``) has
        nothing to say here and a dropped entry can only mean the veto misfired.
        """
        result, _ = await self._run(
            [
                _player_row(11, "Alice", roster_id=4, team=(2, "Team Magma")),
                _player_row(12, "Bob", roster_id=5, team=(3, "Team Rocket")),
            ],
            channels={"alice": (11, "self_declared"), "bob": (12, "verified")},
        )

        self.assertEqual({entry.channel for entry in result.participants}, {"alice", "bob"})
        self.assertTrue(all(entry.player is not None for entry in result.participants))

    async def test_a_player_id_that_resolves_to_nothing_is_withheld(self) -> None:
        # Fail-closed, and deliberately indistinguishable from a veto: a player row we
        # cannot read is a player whose consent we cannot establish.
        result, _ = await self._run([], channels={"ghost": (99, "verified")})

        self.assertEqual(result.participants, [])

    async def test_the_official_broadcast_is_not_touched_by_the_veto(self) -> None:
        # The organizer's slot carries ``player=None`` by design, so the fail-closed
        # participant rule must not reach it -- that would take the tournament's own
        # broadcast off the page whenever the caster happens to have opted out.
        result, _ = await self._run(
            [_player_row(11, "Alice", stream_visible=False)],
            channels={"caster": (11, "official")},
            links=[_link("https://twitch.tv/caster")],
        )

        self.assertEqual([entry.channel for entry in result.official], ["caster"])
        self.assertTrue(result.official[0].live)
        self.assertIsNone(result.official[0].player)
        self.assertEqual(result.participants, [])

    async def test_the_veto_column_rides_the_existing_query(self) -> None:
        channels = {f"p{index}": (20 + index, "verified") for index in range(4)}
        rows = [_player_row(20 + index, f"P{index}") for index in range(4)]

        result, session = await self._run(rows, channels=channels)

        self.assertEqual(len(result.participants), 4)
        # The gate reads a column the batched join already selects, so it must not
        # have cost a statement -- a per-entry consent check would make this len 4.
        self.assertEqual(len(session.executed), 1)
        self.assertIn("stream_visible", str(session.executed[0]))
