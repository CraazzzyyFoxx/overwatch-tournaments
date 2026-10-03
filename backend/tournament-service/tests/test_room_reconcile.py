"""The room's read/write split: a state read is pure, the healer owns the writes.

Every heal the state read used to perform on its way past -- opening the
session, settling an expired step, growing the hero rounds, keeping the series'
games in step with the picks, offering freeplay its next position -- put a
viewer's poll behind the encounter's row lock, and so behind the captains and
behind every other viewer. (Production incident: 647 `SELECT encounter ... FOR
UPDATE` waits up to 2.96s over twenty minutes, from 2977 state GETs.)

So the contract is now:

* ``get_pick_ban_state`` takes no lock, writes nothing, commits nothing and
  signals nothing -- it renders what IS there, however far behind the rules it
  may be;
* ``reconcile_room`` applies every owed heal under the encounter lock, signals
  the kinds that changed, and converges (a second call changes nothing);
* ``reconcile_due_rooms`` is the one-second tick for the only change nobody
  writes: a step's timer running out.

The store is the suite's in-memory ``AsyncSession`` stand-in, extended here to
record every ``FOR UPDATE`` it is handed -- which is the whole point of the
first group of tests.
"""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import MapPickSide, MapPoolEntryStatus, PickBanKind  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterReadiness,
    PickBanEntry,
    PickBanSession,
    PickBanSubmission,
)
from src.services.encounter import room_reconcile  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from tests._pregame_store import _Store, staged_topics  # noqa: E402
from tests.test_pregame_loop import _encounter, _hero_config, _map_config, _turn  # noqa: E402

HOME, AWAY = MapPickSide.HOME.value, MapPickSide.AWAY.value


class _LockTrackingStore(_Store):
    """Remembers every ``FOR UPDATE`` statement it was asked to run."""

    def __init__(self) -> None:
        super().__init__()
        self.locked: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> Any:
        if getattr(statement, "_for_update_arg", None) is not None:
            self.locked.append(self._entity(statement))
        return await super().execute(statement)

    async def commit(self) -> None:
        self.commits += 1
        await super().commit()


def _signals(store: _Store) -> list[str]:
    """The realtime topics staged since the last :func:`_forget_signals`."""
    return staged_topics(store)


def _forget_signals(store: _Store) -> None:
    store.info.pop("realtime_staged", None)


def _rows_of(store: _Store) -> dict[type, int]:
    """Row counts per model -- the "did this read write anything" fingerprint."""
    return {model: len(rows) for model, rows in store.rows.items()}


def _seeded(*, map_config: bool = True, hero_config: bool = False) -> _LockTrackingStore:
    store = _LockTrackingStore()
    encounter = _encounter()
    rows: list[Any] = [encounter]
    if map_config:
        rows.append(_map_config())
    if hero_config:
        rows.append(_hero_config())
    store.seed(*rows)
    store.seed(
        EncounterReadiness(encounter_id=encounter.id, side=HOME, ready_user_id=None),
        EncounterReadiness(encounter_id=encounter.id, side=AWAY, ready_user_id=None),
    )
    store.encounter = encounter  # type: ignore[attr-defined]
    return store


async def _read(store: _Store, kind: PickBanKind = PickBanKind.MAP) -> dict:
    return await pick_ban_action_service.get_pick_ban_state(store, store.encounter.id, kind, viewer_side=HOME)


async def _reconcile(store: _Store, *, skip_locked: bool = False) -> bool:
    return await pick_ban_action_service.reconcile_room(store, store.encounter.id, skip_locked=skip_locked)


async def _ban_out_the_map_round(store: _Store) -> None:
    """Both sides ban this round's first two candidates; the decider takes the
    survivor, which settles the round."""
    for _ in range(2):
        state = await _read(store)
        available = [
            entry["item_id"]
            for entry in state["pool"]
            if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
        ]
        await pick_ban_action_service.perform_pick_ban_action(
            store, store.encounter.id, PickBanKind.MAP, _turn(state), item_id=available[0], action="ban"
        )


def _expire_the_open_step(store: _Store, kind: PickBanKind = PickBanKind.MAP) -> PickBanSession:
    pick_ban = next(row for row in store.all_of(PickBanSession) if row.kind == kind)
    steps = pick_ban.resolved_sequence_json
    steps[0]["timer_seconds"] = 30
    steps[0]["on_timeout"] = "random_fill"
    pick_ban.resolved_sequence_json = steps
    pick_ban.current_step_started_at = datetime.now(UTC) - timedelta(minutes=5)
    return pick_ban


class ReadsAreInertTests(IsolatedAsyncioTestCase):
    """A state read of a room that OWES a heal changes nothing and locks
    nothing. One test per heal the read used to perform."""

    async def _assert_inert(self, store: _LockTrackingStore, kind: PickBanKind = PickBanKind.MAP) -> dict:
        before = _rows_of(store)
        store.locked.clear()
        store.commits = 0
        _forget_signals(store)

        state = await _read(store, kind)

        self.assertEqual([], store.locked, "a read must never take a row lock")
        self.assertEqual(before, _rows_of(store), "a read must write no rows")
        self.assertEqual(0, store.commits, "a read must not commit")
        self.assertEqual([], _signals(store), "a read must publish nothing")
        return state

    async def test_a_room_owing_its_session_renders_as_unavailable(self) -> None:
        store = _seeded()

        state = await self._assert_inert(store)

        self.assertIsNone(state["session"])
        self.assertEqual([], store.all_of(PickBanSession))

    async def test_a_room_owing_an_expired_step_renders_the_step_still_open(self) -> None:
        store = _seeded()
        await _reconcile(store)
        _expire_the_open_step(store)

        state = await self._assert_inert(store)

        self.assertEqual(0, state["current_step_index"])
        self.assertEqual([], store.all_of(PickBanSubmission))

    async def test_a_room_owing_its_games_renders_the_games_it_has(self) -> None:
        store = _seeded()
        await _reconcile(store)
        await _ban_out_the_map_round(store)
        store.rows[EncounterGame] = []

        state = await self._assert_inert(store)

        self.assertEqual([], state["games"])
        self.assertEqual([], store.all_of(EncounterGame))

    async def test_a_room_owing_its_hero_session_renders_hero_as_unavailable(self) -> None:
        store = _seeded(hero_config=True)
        await _reconcile(store)
        await _ban_out_the_map_round(store)
        store.rows[PickBanSession] = [row for row in store.all_of(PickBanSession) if row.kind == PickBanKind.MAP]

        state = await self._assert_inert(store, PickBanKind.HERO)

        self.assertIsNone(state["session"])

    async def test_a_freeplay_room_owing_its_next_position_renders_none(self) -> None:
        store = _seeded(map_config=False)

        state = await self._assert_inert(store)

        self.assertEqual([], state["games"])
        self.assertEqual([], store.all_of(EncounterGame))


class ReconcileAppliesAndConvergesTests(IsolatedAsyncioTestCase):
    """``reconcile_room`` is what heals, what signals, and what stops."""

    async def _assert_settles_once(self, store: _LockTrackingStore, *, topics: list[str]) -> None:
        _forget_signals(store)
        self.assertTrue(await _reconcile(store), "the first pass had work to do")
        self.assertEqual(topics, _signals(store))

        _forget_signals(store)
        self.assertFalse(await _reconcile(store), "a healed room owes nothing")
        self.assertEqual([], _signals(store), "a no-op pass signals nothing")

    async def test_it_opens_the_session_and_then_stops(self) -> None:
        store = _seeded()

        # Twice: creation signals the room itself (every other caller of
        # ``ensure_pick_ban_session`` relies on that), and the pass then signals
        # the kind it changed. Two identical refetch nudges, one transaction.
        await self._assert_settles_once(store, topics=["encounter:1:map-veto", "encounter:1:map-veto"])

        session = store.all_of(PickBanSession)[0]
        self.assertEqual(PickBanKind.MAP, session.kind)
        self.assertEqual([11, 12, 13], sorted(entry.item_id for entry in store.all_of(PickBanEntry)))

    async def test_it_expires_the_step_on_the_clock_and_then_stops(self) -> None:
        store = _seeded()
        await _reconcile(store)
        _expire_the_open_step(store)

        await self._assert_settles_once(store, topics=["encounter:1:map-veto"])

        self.assertEqual([(0, HOME)], [(row.step_index, row.side) for row in store.all_of(PickBanSubmission)])
        self.assertEqual(1, sum(entry.status == MapPoolEntryStatus.BANNED for entry in store.all_of(PickBanEntry)))

    async def test_it_reopens_the_series_game_a_pick_owes_and_then_stops(self) -> None:
        store = _seeded()
        await _reconcile(store)
        await _ban_out_the_map_round(store)
        store.rows[EncounterGame] = []

        await self._assert_settles_once(store, topics=["encounter:1:map-veto"])

        self.assertEqual([(1, 13)], [(game.position, game.map_id) for game in store.all_of(EncounterGame)])

    async def test_it_opens_the_hero_room_once_the_map_round_settles_and_then_stops(self) -> None:
        store = _seeded(hero_config=True)
        await _reconcile(store)
        await _ban_out_the_map_round(store)
        store.rows[PickBanSession] = [row for row in store.all_of(PickBanSession) if row.kind == PickBanKind.MAP]

        _forget_signals(store)
        self.assertTrue(await _reconcile(store))
        self.assertIn("encounter:1:pick-ban:hero", _signals(store))

        _forget_signals(store)
        self.assertFalse(await _reconcile(store))
        self.assertEqual([], _signals(store))

        hero = next(row for row in store.all_of(PickBanSession) if row.kind == PickBanKind.HERO)
        self.assertEqual({1}, {entry.round for entry in store.all_of(PickBanEntry) if entry.session_id == hero.id})

    async def test_it_opens_freeplays_next_position_and_then_stops(self) -> None:
        store = _seeded(map_config=False)

        await self._assert_settles_once(store, topics=["encounter:1:map-veto"])

        self.assertEqual([(1, None)], [(game.position, game.map_id) for game in store.all_of(EncounterGame)])

    async def test_a_room_whose_hero_round_the_append_would_decline_is_never_locked(self) -> None:
        """The precheck mirrors ``advance_to_next_round``'s own refusals.

        Hero round 2 is owed by the series the moment position 1 is confirmed --
        but it cannot open while round 1 still has bans left to take. An "owed"
        answer here would lock the encounter on every pass of both sweeps and
        change nothing, forever.
        """
        store = _seeded(hero_config=True)
        await _reconcile(store)
        await _ban_out_the_map_round(store)
        await _reconcile(store)
        game = store.all_of(EncounterGame)[0]
        game.accepted_home_score, game.accepted_away_score = 2, 1
        game.state = type(game.state).CONFIRMED

        store.locked.clear()
        self.assertFalse(await _reconcile(store))
        self.assertEqual([], store.locked, "an unlocked precheck answered it")


class DueRoomTickTests(IsolatedAsyncioTestCase):
    """The one-second tick: the only heal nothing writes is a step's timer."""

    def _patch_session_maker(self, store: _Store) -> None:
        @contextlib.asynccontextmanager
        async def _maker() -> Any:
            yield store

        original = room_reconcile.db.async_session_maker
        room_reconcile.db.async_session_maker = _maker
        self.addCleanup(lambda: setattr(room_reconcile.db, "async_session_maker", original))

    async def test_it_settles_an_expired_step(self) -> None:
        store = _seeded()
        await _reconcile(store)
        _expire_the_open_step(store)
        self._patch_session_maker(store)

        await room_reconcile.reconcile_due_rooms()

        self.assertEqual([(0, HOME)], [(row.step_index, row.side) for row in store.all_of(PickBanSubmission)])

    async def test_it_leaves_a_paused_room_alone(self) -> None:
        store = _seeded()
        await _reconcile(store)
        pick_ban = _expire_the_open_step(store)
        # A paused session is untimed by ``step_deadline``, so its step can never
        # come due however long the organizer leaves it frozen.
        pick_ban.paused_at = datetime.now(UTC)
        self._patch_session_maker(store)

        await room_reconcile.reconcile_due_rooms()

        self.assertEqual([], store.all_of(PickBanSubmission))

    async def test_it_leaves_a_step_whose_timer_is_still_running(self) -> None:
        store = _seeded()
        await _reconcile(store)
        pick_ban = next(row for row in store.all_of(PickBanSession) if row.kind == PickBanKind.MAP)
        steps = pick_ban.resolved_sequence_json
        steps[0]["timer_seconds"] = 300
        steps[0]["on_timeout"] = "random_fill"
        pick_ban.resolved_sequence_json = steps
        pick_ban.current_step_started_at = datetime.now(UTC)
        self._patch_session_maker(store)

        await room_reconcile.reconcile_due_rooms()

        self.assertEqual([], store.all_of(PickBanSubmission))

    async def test_it_never_locks_a_wait_step_that_outlived_its_timer(self) -> None:
        store = _seeded()
        await _reconcile(store)
        pick_ban = _expire_the_open_step(store)
        # ``wait`` keeps the step open past its deadline; nothing is owed, so the
        # tick must not take the room's lock every second to find that out.
        pick_ban.resolved_sequence_json = [{**pick_ban.resolved_sequence_json[0], "on_timeout": "wait"}] + list(
            pick_ban.resolved_sequence_json[1:]
        )
        store.locked.clear()
        self._patch_session_maker(store)

        await room_reconcile.reconcile_due_rooms()

        self.assertEqual([], store.all_of(PickBanSubmission))
        self.assertEqual([], store.locked)
