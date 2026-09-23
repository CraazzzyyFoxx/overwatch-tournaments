"""Undo-by-consent for the pick-ban room (``services.encounter.pick_ban_undo``).

DB-free: ``perform_undo``'s only queries are the session lookup, the pool load,
one count and one ledger delete, so a fake session that serves those four is
enough to exercise the whole consent state machine -- which is where the
behavior lives (who may apply an undo, and what a revert restores).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    EncounterGameState,
    EncounterStatus,
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoSessionStatus,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.services.encounter import pick_ban_undo  # noqa: E402
from src.services.encounter.pick_ban_action import apply_pick_ban_action  # noqa: E402


def staged_topics(session: object) -> list[str]:
    """The realtime topics ``emit`` staged on this session, in call order.

    The topic is the whole contract for a pick-ban signal: it names the room
    that must refetch, and the payload adds nothing a subscriber branches on.
    """
    staged = getattr(session, "info", {}).get("realtime_staged")
    if staged is None:
        return []
    return [scope.domain_topic(data.domain) for scope, data, _actor in staged.domain]


def entry(
    item_id: int,
    *,
    status: MapPoolEntryStatus = MapPoolEntryStatus.AVAILABLE,
    picked_by: MapPickSide | str | None = None,
    protected_by: MapPickSide | str | None = None,
    round: int | None = 1,
    action_index: int | None = None,
    order: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        item_id=item_id,
        status=status.value if isinstance(status, MapPoolEntryStatus) else status,
        picked_by=picked_by.value if isinstance(picked_by, MapPickSide) else picked_by,
        protected_by=protected_by.value if isinstance(protected_by, MapPickSide) else protected_by,
        round=round,
        action_index=action_index,
        order=order,
    )


def pick_ban_session(**overrides) -> SimpleNamespace:
    base = {
        "id": 9,
        "resolved_sequence_json": ["ban_home", "ban_away", "decider"],
        "status": MapVetoSessionStatus.ACTIVE.value,
        "undo_requested_by": None,
        "undo_target_index": None,
        "current_step_started_at": datetime.now(UTC) - timedelta(minutes=5),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeSession:
    """Serves the statements ``perform_undo`` issues, and records the ledger
    deletes so a revert's cross-round cleanup is observable.

    A MAP undo additionally reads the series' positions (``EncounterGame``) and
    their claims (``EncounterMapReport``) -- an undo that would strand a played
    map is refused -- and, once applied, re-syncs the games against what is left
    picked.
    """

    def __init__(
        self,
        pool: list[SimpleNamespace],
        *,
        hero_committed: int = 0,
        games: list[SimpleNamespace] | None = None,
        reports: list[SimpleNamespace] | None = None,
        encounter: SimpleNamespace | None = None,
    ) -> None:
        self.pool = pool
        self.hero_committed = hero_committed
        self.games = games or []
        self.reports = reports or []
        self.encounter = encounter
        self.commits = 0
        self.deletes: list[object] = []
        self.info: dict = {}

    def _rows_for(self, statement: object) -> list:
        name = getattr(statement.column_descriptions[0]["entity"], "__name__", "")
        if name == "EncounterGame":
            return [game for game in self.games if game.state != EncounterGameState.CANCELLED]
        if name == "EncounterMapReport":
            return list(self.reports)
        if name == "Encounter":
            return [self.encounter] if self.encounter is not None else []
        return list(self.pool)

    async def execute(self, statement: object) -> object:
        if statement.__class__.__name__ == "Delete":
            self.deletes.append(statement)
            return SimpleNamespace()
        rows = self._rows_for(statement)

        class _Result:
            def unique(self_inner) -> object:
                return self_inner

            def scalars(self_inner) -> object:
                return SimpleNamespace(all=lambda: list(rows), first=lambda: rows[0] if rows else None)

        return _Result()

    async def scalar(self, statement: object) -> int:
        return self.hero_committed

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _game(position: int, *, state: EncounterGameState = EncounterGameState.AWAITING_RESULT) -> SimpleNamespace:
    return SimpleNamespace(
        id=700 + position,
        encounter_id=500,
        position=position,
        map_id=20 + position,
        state=state,
        accepted_home_score=None,
        accepted_away_score=None,
    )


async def _run_undo(
    pool: list[SimpleNamespace],
    pick_ban: SimpleNamespace,
    side: str,
    *,
    consent: bool = True,
    kind: PickBanKind = PickBanKind.HERO,
    hero_session: SimpleNamespace | None = None,
    hero_committed: int = 0,
    games: list[SimpleNamespace] | None = None,
    reports: list[SimpleNamespace] | None = None,
) -> tuple[_FakeSession, dict]:
    """`perform_undo` against a fake session, with the session lookup stubbed
    per kind (a map undo also asks for the hero session)."""
    session = _FakeSession(
        pool,
        hero_committed=hero_committed,
        games=games,
        reports=reports,
        encounter=SimpleNamespace(id=500, best_of=3, status=EncounterStatus.OPEN, home_score=0, away_score=0),
    )

    async def get_pick_ban_session(_session, _encounter_id, wanted_kind, *, for_update: bool = False):
        if wanted_kind == kind:
            return pick_ban
        return hero_session

    with patch.object(pick_ban_undo.pick_ban_session_service, "get_pick_ban_session", get_pick_ban_session):
        state = await pick_ban_undo.pick_ban_undo_service.perform_undo(session, 500, kind, side, consent=consent)
    return session, state


class UndoStateTests(TestCase):
    def test_reports_nothing_undoable_on_a_fresh_pool(self) -> None:
        state = pick_ban_undo.undo_state(pick_ban_session(), [entry(1), entry(2)])

        self.assertEqual(
            {"requested_by": None, "item_ids": [], "action": None, "side": None},
            state,
        )

    def test_names_the_last_action_and_who_asked(self) -> None:
        pool = [
            entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(2),
        ]
        state = pick_ban_undo.undo_state(pick_ban_session(undo_requested_by="away", undo_target_index=0), pool)

        self.assertEqual("away", state["requested_by"])
        self.assertEqual([1], state["item_ids"])
        self.assertEqual("ban", state["action"])
        self.assertEqual("home", state["side"])

    def test_a_request_against_a_superseded_action_reads_as_no_request(self) -> None:
        # The consent was given when action 0 was last; action 1 has landed since.
        pool = [
            entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(2, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.AWAY, action_index=1),
        ]
        state = pick_ban_undo.undo_state(pick_ban_session(undo_requested_by="away", undo_target_index=0), pool)

        self.assertIsNone(state["requested_by"])
        self.assertEqual([2], state["item_ids"])

    def test_lists_a_decider_it_would_revert_alongside_the_action(self) -> None:
        pool = [
            entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(2, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.DECIDER, action_index=1),
        ]
        state = pick_ban_undo.undo_state(pick_ban_session(), pool)

        # Play order, so the room reads them the way they were committed.
        self.assertEqual([1, 2], state["item_ids"])
        self.assertEqual("ban", state["action"])


class ApplyUndoTests(TestCase):
    def test_reverts_the_entries_and_reopens_a_completed_session(self) -> None:
        banned = entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0)
        pick_ban = pick_ban_session(
            status=MapVetoSessionStatus.COMPLETED.value,
            undo_requested_by="away",
            undo_target_index=0,
        )
        before = pick_ban.current_step_started_at

        pick_ban_undo.apply_undo(pick_ban, [banned], now=datetime.now(UTC))

        self.assertEqual(MapPoolEntryStatus.AVAILABLE.value, banned.status)
        self.assertIsNone(banned.picked_by)
        self.assertIsNone(banned.action_index)
        self.assertEqual(MapVetoSessionStatus.ACTIVE.value, pick_ban.status)
        self.assertIsNone(pick_ban.undo_requested_by)
        self.assertIsNone(pick_ban.undo_target_index)
        # A fresh turn clock: the restored step's old deadline is long gone, and
        # `auto_resolve_timeout` would otherwise re-take the action at random on
        # the very next read.
        self.assertGreater(pick_ban.current_step_started_at, before)

    def test_ledger_keys_name_only_the_bans(self) -> None:
        bans = [
            entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(2, status=MapPoolEntryStatus.PROTECTED, protected_by=MapPickSide.HOME, action_index=1),
            entry(3, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.DECIDER, action_index=2),
        ]

        self.assertEqual([(1, "home")], pick_ban_undo.ledger_keys(bans))


class PerformUndoTests(IsolatedAsyncioTestCase):
    def _banned_pool(self) -> list[SimpleNamespace]:
        return [
            entry(101, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(102),
            entry(103),
        ]

    async def test_the_first_call_only_records_the_request(self) -> None:
        pool = self._banned_pool()
        pick_ban = pick_ban_session()

        session, state = await _run_undo(pool, pick_ban, "home")

        self.assertEqual("home", pick_ban.undo_requested_by)
        self.assertEqual(0, pick_ban.undo_target_index)
        self.assertEqual("home", state["requested_by"])
        # Nothing reverted yet -- one side is not an agreement.
        self.assertEqual(MapPoolEntryStatus.BANNED.value, pool[0].status)
        self.assertEqual(1, session.commits)
        self.assertEqual(["encounter:500:pick-ban:hero"], staged_topics(session))

    async def test_the_same_side_asking_twice_changes_nothing(self) -> None:
        pool = self._banned_pool()
        pick_ban = pick_ban_session(undo_requested_by="home", undo_target_index=0)

        _session, _state = await _run_undo(pool, pick_ban, "home")

        self.assertEqual("home", pick_ban.undo_requested_by)
        self.assertEqual(MapPoolEntryStatus.BANNED.value, pool[0].status)

    async def test_the_opponent_agreeing_applies_the_undo(self) -> None:
        pool = self._banned_pool()
        pick_ban = pick_ban_session(undo_requested_by="home", undo_target_index=0)

        session, state = await _run_undo(pool, pick_ban, "away")

        self.assertEqual(MapPoolEntryStatus.AVAILABLE.value, pool[0].status)
        self.assertIsNone(pool[0].picked_by)
        self.assertIsNone(pool[0].action_index)
        self.assertIsNone(pick_ban.undo_requested_by)
        # The reverted ban's cross-round memory goes with it, or a later round
        # would still be excluding a hero nobody banned.
        self.assertEqual(1, len(session.deletes))
        # Nothing is undoable any more: the pool is back to untouched.
        self.assertEqual([], state["item_ids"])

    async def test_withdrawing_clears_the_request_without_reverting(self) -> None:
        pool = self._banned_pool()
        pick_ban = pick_ban_session(undo_requested_by="home", undo_target_index=0)

        session, state = await _run_undo(pool, pick_ban, "home", consent=False)

        self.assertIsNone(pick_ban.undo_requested_by)
        self.assertIsNone(state["requested_by"])
        self.assertEqual(MapPoolEntryStatus.BANNED.value, pool[0].status)
        self.assertEqual([], session.deletes)

    async def test_declining_from_the_other_side_clears_it_too(self) -> None:
        pool = self._banned_pool()
        pick_ban = pick_ban_session(undo_requested_by="home", undo_target_index=0)

        _session, _state = await _run_undo(pool, pick_ban, "away", consent=False)

        self.assertIsNone(pick_ban.undo_requested_by)
        self.assertEqual(MapPoolEntryStatus.BANNED.value, pool[0].status)

    async def test_a_stale_request_is_replaced_rather_than_applied(self) -> None:
        # home's consent was given against action 0; action 1 landed since, so
        # away's call must open a fresh request for action 1, not undo it.
        pool = [
            entry(101, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(102, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.AWAY, action_index=1),
            entry(103),
        ]
        pick_ban = pick_ban_session(undo_requested_by="home", undo_target_index=0)

        _session, state = await _run_undo(pool, pick_ban, "away")

        self.assertEqual("away", pick_ban.undo_requested_by)
        self.assertEqual(1, pick_ban.undo_target_index)
        self.assertEqual([102], state["item_ids"])
        self.assertEqual(MapPoolEntryStatus.BANNED.value, pool[1].status)

    async def test_nothing_to_undo_is_a_400(self) -> None:
        pool = [entry(101), entry(102)]

        with self.assertRaises(HTTPException) as ctx:
            await _run_undo(pool, pick_ban_session(), "home")

        self.assertEqual(400, ctx.exception.status_code)
        self.assertEqual("There is no action left to undo", ctx.exception.detail)

    async def test_a_map_undo_waits_on_this_rounds_hero_bans(self) -> None:
        # The hero round opened off this map pick and is never withdrawn, so
        # taking the pick back with bans standing would orphan them.
        pool = [
            entry(21, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.HOME, action_index=0),
            entry(22),
        ]
        with self.assertRaises(HTTPException) as ctx:
            await _run_undo(
                pool,
                pick_ban_session(),
                "home",
                kind=PickBanKind.MAP,
                hero_session=pick_ban_session(id=10),
                hero_committed=1,
            )

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("hero bans first", ctx.exception.detail)

    async def test_a_map_undo_goes_through_once_no_hero_ban_stands(self) -> None:
        pool = [
            entry(21, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.HOME, action_index=0),
            entry(22),
        ]
        await _run_undo(
            pool,
            pick_ban_session(undo_requested_by="away", undo_target_index=0),
            "home",
            kind=PickBanKind.MAP,
            hero_session=pick_ban_session(id=10),
            hero_committed=0,
        )

        self.assertEqual(MapPoolEntryStatus.AVAILABLE.value, pool[0].status)

    async def test_map_undo_is_refused_once_the_game_has_a_claim(self) -> None:
        """A pick opens a series position. Taking it back cancels that position,
        so a captain's claim already standing on it would be dropped on a click
        -- two captains agreeing to change a MAP must never move a result."""
        pool = [
            entry(21, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.HOME, action_index=0),
            entry(22),
        ]

        with self.assertRaises(HTTPException) as ctx:
            await _run_undo(
                pool,
                pick_ban_session(undo_requested_by="away", undo_target_index=0),
                "home",
                kind=PickBanKind.MAP,
                hero_session=None,
                games=[_game(1)],
                reports=[SimpleNamespace(id=1, game_id=701, side="home", home_score=2, away_score=1)],
            )

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("already has a result claim", ctx.exception.detail)
        self.assertEqual(MapPoolEntryStatus.PICKED.value, pool[0].status, "the pick stands")

    async def test_map_undo_is_refused_once_the_game_is_confirmed(self) -> None:
        pool = [
            entry(21, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.HOME, action_index=0),
            entry(22),
        ]

        with self.assertRaises(HTTPException) as ctx:
            await _run_undo(
                pool,
                pick_ban_session(undo_requested_by="away", undo_target_index=0),
                "home",
                kind=PickBanKind.MAP,
                hero_session=None,
                games=[_game(1, state=EncounterGameState.CONFIRMED)],
            )

        self.assertEqual(400, ctx.exception.status_code)

    async def test_map_undo_cancels_the_unclaimed_game(self) -> None:
        """Nothing was claimed, so the position the pick opened is retired with
        it -- leaving it would let captains report a map that is no longer in
        the series."""
        pool = [
            entry(21, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.HOME, action_index=0),
            entry(22),
        ]
        game = _game(1)

        session, _state = await _run_undo(
            pool,
            pick_ban_session(undo_requested_by="away", undo_target_index=0),
            "home",
            kind=PickBanKind.MAP,
            hero_session=None,
            games=[game],
        )

        self.assertEqual(MapPoolEntryStatus.AVAILABLE.value, pool[0].status)
        self.assertEqual(EncounterGameState.CANCELLED, game.state)
        self.assertEqual(1, session.commits)


class ConsentLifetimeTests(TestCase):
    def test_a_new_action_drops_an_open_request(self) -> None:
        """A consent is given for ONE action. The next action supersedes it, so
        the agreement must not survive into a state nobody read."""
        pick_ban = pick_ban_session(
            resolved_sequence_json=["ban_home", "ban_away", "decider"],
            undo_requested_by="away",
            undo_target_index=0,
        )
        pool = [
            entry(101, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            entry(102),
            entry(103),
        ]

        apply_pick_ban_action(
            pick_ban,
            pool,
            captain_side="away",
            item_id=102,
            action="ban",
            attribute_lookup={},
            unique_attribute=None,
            now=datetime.now(UTC),
        )

        self.assertIsNone(pick_ban.undo_requested_by)
        self.assertIsNone(pick_ban.undo_target_index)


class UndoLocksTheSessionTests(IsolatedAsyncioTestCase):
    """An undo REMOVES a committed entry, which moves the step cursor exactly
    as taking one does -- so it belongs behind the same lock, and the consent
    it compares (``undo_target_index`` against the pool's trailing action) is
    read under it."""

    async def test_perform_undo_asks_for_the_row_locked(self) -> None:
        seen: list[bool] = []

        class _Stop(Exception):
            pass

        async def spy(_session, _encounter_id, _kind, *, for_update: bool = False):
            seen.append(for_update)
            raise _Stop

        with patch.object(pick_ban_undo.pick_ban_session_service, "get_pick_ban_session", spy):
            with self.assertRaises(_Stop):
                await pick_ban_undo.pick_ban_undo_service.perform_undo(_FakeSession([]), 500, PickBanKind.HERO, "home")

        self.assertEqual([True], seen)
