"""The native match document (P7 contracts §6): arbitrary participants, every grain of fact, no home/away.

Real rows on the migrated parity schema, read through the production readers. The fixture is the integrated
acceptance case: three participants whose source order is reversed against their seats, one without a source team,
one event-only member, a missing ``played_at``, an inactive stat and character, positive segments next to the
whole-match segment, another workspace's member of the same global player, and a character of another game.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models
from shared.core.errors import BaseAPIException
from shared.services.tournament.visibility import ensure_tournament_viewable
from shared.testing.stats_parity import _DATES, BASE, STAMP, _insert, seed_native_sentinel
from src import schemas
from src.services.admin.matches import matches_service
from src.services.encounter.flows import flows_service as encounters
from src.services.visibility_resolvers import visibility_resolvers_service as visibility

ENCOUNTER = BASE + 600
SEATS = (BASE + 600, BASE + 601, BASE + 602)
UNBOUND, BOUND = BASE + 600, BASE + 601
GAME = BASE + 600


async def _uncached(method: Any, *args: Any, **kwargs: Any) -> Any:
    return await inspect.unwrap(method.__func__)(method.__self__, *args, **kwargs)


def _seed(conn: sa.Connection, ids: dict[str, int]) -> dict[str, int]:
    """One 3-seat encounter of the OW tournament with an unbound and a game-bound observation."""
    rule = conn.scalar(
        sa.text("SELECT scoring_rule_id FROM encounter.encounter WHERE id = :id"), {"id": ids["encounter"]}
    )
    _insert(
        conn,
        "encounter.encounter",
        id=ENCOUNTER,
        workspace_id=ids["workspace"],
        discipline="overwatch",
        tournament_id=ids["tournament"],
        scoring_rule_id=rule,
        name="P7 three seats",
        slot_count=3,
        status="COMPLETED",
        result_status="confirmed",
        result_source="admin",
        confirmed_at=STAMP,
        **_DATES,
    )
    for seat, slot, team, name in zip(
        SEATS, (1, 2, 3), (ids["team_home"], ids["team_away"], None), ("Seat one", "Seat two", "Walk-in"), strict=True
    ):
        _insert(
            conn,
            "encounter.team",
            id=seat,
            encounter_id=ENCOUNTER,
            tournament_id=ids["tournament"],
            team_id=team,
            slot=slot,
            name=name,
            **_DATES,
        )
    _insert(
        conn,
        "encounter.game",
        id=GAME,
        encounter_id=ENCOUNTER,
        position=1,
        map_id=ids["map"],
        state="confirmed",
        result_source="admin",
        confirmed_at=STAMP,
        **_DATES,
    )
    # An official line for two of the three seats only; the third has none.
    _insert(
        conn,
        "encounter.game_team",
        game_id=GAME,
        encounter_id=ENCOUNTER,
        encounter_team_id=SEATS[0],
        score=13,
        placement=1,
    )
    _insert(
        conn,
        "encounter.game_team",
        game_id=GAME,
        encounter_id=ENCOUNTER,
        encounter_team_id=SEATS[1],
        score=7,
        placement=2,
    )

    stat = {
        code: conn.scalar(
            sa.text("SELECT id FROM stats.stat_def WHERE discipline='overwatch' AND code=:c"), {"c": code}
        )
        for code in ("score", "hero_damage_dealt", "hero_time_played", "barrier_damage_dealt")
    }
    kind = {
        code: conn.scalar(
            sa.text("SELECT id FROM stats.event_type WHERE discipline='overwatch' AND code=:c"), {"c": code}
        )
        for code in ("kill", "ultimate_start")
    }
    # Inactive history: a deactivated stat and a deactivated character keep their facts readable.
    conn.execute(
        sa.text("UPDATE stats.stat_def SET active = false WHERE id = :id"), {"id": stat["barrier_damage_dealt"]}
    )
    conn.execute(sa.text("UPDATE catalog.entity SET active = false WHERE id = :id"), {"id": ids["hero_other"]})

    for match, game, played_at in ((UNBOUND, None, None), (BOUND, GAME, STAMP + timedelta(hours=1))):
        _insert(
            conn,
            "stats.match",
            id=match,
            workspace_id=ids["workspace"],
            discipline="overwatch",
            encounter_id=ENCOUNTER,
            encounter_game_id=game,
            source_map_index=1,
            map_entity_id=ids["map"],
            duration_s=300.0 if game is None else 420.0,
            played_at=played_at,
            **_DATES,
        )
    for match in (UNBOUND, BOUND):
        # Source order is reversed against the seats: seat one is third in the log, seat two first.
        for seat, position in zip(SEATS, (3, 1, 2), strict=True):
            _insert(
                conn,
                "stats.match_team",
                match_id=match,
                encounter_id=ENCOUNTER,
                encounter_team_id=seat,
                source_position=position,
            )
    members = (
        (SEATS[0], ids["member"], "Alpha#1"),
        (SEATS[1], ids["member_away"], "Bravo#1"),
        # Event-only: observed on the third seat, with no fact at all.
        (SEATS[2], ids["member_event_only"], "Substitute#1"),
    )
    for match in (UNBOUND, BOUND):
        for seat, member, handle in members:
            _insert(
                conn,
                "stats.match_player",
                match_id=match,
                encounter_team_id=seat,
                workspace_member_id=member,
                handle_snapshot=handle,
            )

    def fact(
        match: int,
        seat: int,
        stat_id: int,
        value: float,
        *,
        member: int | None = None,
        entity: int | None = None,
        segment: int = 0,
    ) -> None:
        _insert(
            conn,
            "stats.fact",
            match_id=match,
            segment=segment,
            encounter_team_id=seat,
            workspace_member_id=member,
            entity_id=entity,
            stat_id=stat_id,
            value=value,
        )

    # Team facts: seat one and two observed a score; seat three has none (missing, never zero).
    fact(UNBOUND, SEATS[0], stat["score"], 2.0)
    fact(UNBOUND, SEATS[1], stat["score"], 1.0)
    fact(BOUND, SEATS[0], stat["score"], 2.0)
    fact(BOUND, SEATS[1], stat["score"], 1.0)
    alpha, bravo = ids["member"], ids["member_away"]
    for match in (UNBOUND, BOUND):
        # Whole match and two rounds, each its own observation; none is a sum of the others.
        for segment, value in ((0, 1000.0), (1, 600.0), (2, 400.0)):
            fact(match, SEATS[0], stat["hero_damage_dealt"], value, member=alpha, segment=segment)
        fact(match, SEATS[1], stat["hero_damage_dealt"], 250.0, member=bravo)
        # The member's total is independent of the per-character rows below it.
        fact(match, SEATS[0], stat["hero_time_played"], 450.0, member=alpha)
        fact(match, SEATS[0], stat["hero_time_played"], 300.0, member=alpha, entity=ids["hero"])
        fact(match, SEATS[0], stat["hero_time_played"], 100.0, member=alpha, entity=ids["hero_other"])
        fact(match, SEATS[0], stat["barrier_damage_dealt"], 5.0, member=alpha)
    # Another workspace's member of the same global player never leaks into this match.
    _insert(
        conn,
        "stats.match_player",
        match_id=UNBOUND,
        encounter_team_id=SEATS[0],
        workspace_member_id=ids["member_other"],
        handle_snapshot="Foreign#1",
    )
    fact(UNBOUND, SEATS[0], stat["hero_damage_dealt"], 999999.0, member=ids["member_other"])
    # A character of another game is not a character of this match.
    seed_native_sentinel(conn, ids)
    fact(UNBOUND, SEATS[0], stat["hero_time_played"], 77.0, member=alpha, entity=ids["hero_lol"], segment=3)
    for segment in (1, 2):
        _insert(conn, "stats.segment", match_id=UNBOUND, segment=segment, kind="round", attrs={"n": segment})
    for t, segment, type_id, actor, target, entity in (
        (5.0, 1, kind["kill"], (alpha, SEATS[0]), (bravo, SEATS[1]), ids["hero"]),
        (3.0, 1, kind["ultimate_start"], (alpha, SEATS[0]), (None, None), None),
        (1.0, 2, kind["ultimate_start"], (None, None), (None, None), None),
    ):
        _insert(
            conn,
            "stats.event",
            match_id=UNBOUND,
            segment=segment,
            t=t,
            type_id=type_id,
            actor_member_id=actor[0],
            actor_team_id=actor[1],
            target_member_id=target[0],
            target_team_id=target[1],
            entity_id=entity,
            related_entity_id=ids["hero_lol"] if entity else None,
        )
    conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    return ids


def _run(stats_parity_database, body):
    async def exercise():
        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await session.run_sync(lambda sync: _seed(sync.connection(), ids))
                return await body(session, ids)
        finally:
            await engine.dispose()

    return asyncio.run(exercise())


def test_three_participants_keep_their_own_order_source_and_missing_facts(stats_parity_database):
    async def body(session: AsyncSession, ids: dict[str, int]) -> None:
        match = await _uncached(encounters.get_match_with_stats, session, UNBOUND, [], workspace_id=ids["workspace"])
        # Public order is the seat; the log's order is each participant's own source position.
        assert [
            (p.encounter_team_id, p.slot, p.source_position, p.tournament_team_id, p.name) for p in match.participants
        ] == [
            (SEATS[0], 1, 3, ids["team_home"], "Seat one"),
            (SEATS[1], 2, 1, ids["team_away"], "Seat two"),
            (SEATS[2], 3, 2, None, "Walk-in"),
        ]
        # An unbound match has no official result; an unobserved score is an absent key, never zero.
        assert [p.result for p in match.participants] == [None, None, None]
        assert [p.team_facts for p in match.participants] == [{"score": 2.0}, {"score": 1.0}, {}]
        assert (match.played_at, match.map_index, match.encounter_game_id) == (None, None, None)
        assert (match.workspace_id, match.discipline, match.duration_s) == (ids["workspace"], "overwatch", 300.0)
        assert {"score", "home_participation", "away_participation", "rounds", "time"}.isdisjoint(match.model_dump())

    _run(stats_parity_database, body)


def test_members_are_this_matchs_observed_players_and_never_another_workspaces(stats_parity_database):
    async def body(session: AsyncSession, ids: dict[str, int]) -> None:
        statistics = (
            await _uncached(encounters.get_match_with_stats, session, UNBOUND, [], workspace_id=ids["workspace"])
        ).statistics
        # Event-only members stay; the other workspace's member of the same global player is not a participant.
        # ``display.canonical`` is the canonical ``players.user.name``, never the observation's handle; the shown name
        # is the observed handle here (no workspace name, no visible game account).
        assert [
            (
                m.encounter_team_id,
                m.workspace_member_id,
                m.player_id,
                m.display.canonical,
                m.display.name,
                m.handle_snapshot,
            )
            for m in statistics.members
        ] == [
            (SEATS[0], ids["member"], ids["player"], "P4 Alpha", "Alpha", "Alpha#1"),
            (SEATS[1], ids["member_away"], ids["player_away"], "P4 Bravo", "Bravo", "Bravo#1"),
            (
                SEATS[2],
                ids["member_event_only"],
                ids["player_event_only"],
                "P4 Substitute",
                "Substitute",
                "Substitute#1",
            ),
        ]
        assert all(fact.workspace_member_id != ids["member_other"] for fact in statistics.facts)
        assert 999999.0 not in {fact.value for fact in statistics.facts}
        assert [f for f in statistics.facts if f.workspace_member_id == ids["member_event_only"]] == []

    _run(stats_parity_database, body)


def test_every_grain_is_kept_apart_with_raw_values_and_no_double_counting(stats_parity_database):
    async def body(session: AsyncSession, ids: dict[str, int]) -> None:
        statistics = (
            await _uncached(encounters.get_match_with_stats, session, UNBOUND, [], workspace_id=ids["workspace"])
        ).statistics
        alpha = ids["member"]

        def values(code: str, **where: Any) -> list[float]:
            return [
                f.value
                for f in statistics.facts
                if f.stat_code == code and all(getattr(f, key) == value for key, value in where.items())
            ]

        # Segment zero is the whole match; positive segments are their own observations, never added to it.
        assert values("hero_damage_dealt", workspace_member_id=alpha, entity_id=None) == [1000.0, 600.0, 400.0]
        assert [s.segment for s in statistics.segments] == [1, 2]
        assert [(s.kind, s.attrs) for s in statistics.segments] == [("round", {"n": 1}), ("round", {"n": 2})]
        # A member's total and its per-character rows are separate facts; the total is not their sum.
        assert values("hero_time_played", workspace_member_id=alpha, entity_id=None) == [450.0]
        assert sorted(values("hero_time_played", workspace_member_id=alpha, entity_id=ids["hero"])) == [300.0]
        assert sorted(values("hero_time_played", workspace_member_id=alpha, entity_id=ids["hero_other"])) == [100.0]
        # Team facts have neither member nor entity; the missing seat has none.
        assert [(f.encounter_team_id, f.value) for f in statistics.facts if f.stat_code == "score"] == [
            (SEATS[0], 2.0),
            (SEATS[1], 1.0),
        ]
        assert all(
            f.workspace_member_id is None and f.entity_id is None for f in statistics.facts if f.stat_code == "score"
        )
        # Inactive stats and characters are history, still served; a character of another game never is.
        assert values("barrier_damage_dealt", workspace_member_id=alpha) == [5.0]
        assert {(e.id, e.active, e.discipline) for e in statistics.entities} == {
            (ids["hero"], True, "overwatch"),
            (ids["hero_other"], False, "overwatch"),
        }
        assert all(f.entity_id != ids["hero_lol"] for f in statistics.facts)
        order = [
            (f.segment, f.encounter_team_id, f.workspace_member_id is not None, f.entity_id is not None)
            for f in statistics.facts
        ]
        assert order == sorted(order), "ordered by segment, team, member NULLS FIRST, entity NULLS FIRST"

    _run(stats_parity_database, body)


def test_the_bound_match_carries_official_lines_apart_from_what_was_observed(stats_parity_database):
    async def body(session: AsyncSession, ids: dict[str, int]) -> None:
        match = await _uncached(encounters.get_match_with_stats, session, BOUND, [], workspace_id=ids["workspace"])
        assert (match.map_index, match.encounter_game_id) == (1, GAME)
        assert match.played_at == STAMP + timedelta(hours=1)
        assert [
            (p.encounter_team_id, p.result and (p.result.score, p.result.placement)) for p in match.participants
        ] == [
            (SEATS[0], (13, 1)),
            (SEATS[1], (7, 2)),
            # No line for the third seat: none is invented from the observed facts.
            (SEATS[2], None),
        ]
        # The observation still says what the log said, not what the tournament decided.
        assert [p.team_facts.get("score") for p in match.participants] == [2.0, 1.0, None]

    _run(stats_parity_database, body)


def test_the_timeline_keeps_every_declared_type_in_order_with_same_game_characters(stats_parity_database):
    async def body(session: AsyncSession, ids: dict[str, int]) -> None:
        feed = await _uncached(encounters.get_match_kill_feed, session, UNBOUND, workspace_id=ids["workspace"])
        assert (feed.match_id, feed.discipline) == (UNBOUND, "overwatch")
        assert [(e.segment, e.t, e.type) for e in feed.events] == [
            (1, 3.0, "ultimate_start"),
            (1, 5.0, "kill"),
            (2, 1.0, "ultimate_start"),
        ]
        kill = next(e for e in feed.events if e.type == "kill")
        # The character of another game is not named; the actor and target are seats and members, not users.
        assert (kill.entity_id, kill.related_entity_id) == (ids["hero"], None)
        assert (kill.actor_member_id, kill.actor_team_id) == (ids["member"], SEATS[0])
        assert (kill.target_member_id, kill.target_team_id) == (ids["member_away"], SEATS[1])
        assert [e.id for e in feed.entities] == [ids["hero"]]

    _run(stats_parity_database, body)


def test_a_hidden_tournaments_match_is_not_public_but_its_admin_reads_stay(stats_parity_database):
    async def body(session: AsyncSession, ids: dict[str, int]) -> None:
        public = await _uncached(encounters.get_all_matches, session, schemas.MatchSearchParams(per_page=-1))
        assert {UNBOUND, BOUND} <= {row.id for row in public.results}
        await session.execute(
            sa.update(models.Tournament).where(models.Tournament.id == ids["tournament"]).values(is_hidden=True)
        )
        owner = await visibility.tournament_id_for_match(session, UNBOUND)
        assert owner == ids["tournament"]
        with pytest.raises(BaseAPIException) as caught:
            await ensure_tournament_viewable(session, None, owner)
        assert caught.value.status_code == 404
        hidden = await _uncached(encounters.get_all_matches, session, schemas.MatchSearchParams(per_page=-1))
        assert not {UNBOUND, BOUND} & {row.id for row in hidden.results}
        # The workspace's own admin still reads the full header, every participant included.
        detail = await matches_service.get_admin_match(session, workspace_id=ids["workspace"], match_id=UNBOUND)
        assert [p.encounter_team_id for p in detail.participants] == list(SEATS)
        assert detail.map.id == ids["map"]

    _run(stats_parity_database, body)
