"""The organizer's pre-game surfaces: the readiness override and the
tournament-wide rooms board.

Two things are pinned here. First the SIGNAL a captain's ready now carries --
nothing polls a room while no session exists, so an unsignalled insert leaves
the opposite captain's screen stale until they reload. Second the derivation
the board is: its ``phase``/``attention`` ranking is pure, so most of it is
exercised as plain functions, and the handful of store-backed cases check that
the bulk reads feed those functions what they should (and that a read of the
board writes NOTHING -- the room's own read creates sessions, this one must not).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    EncounterGameState,
    EncounterResultStatus,
    EncounterStatus,
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoSessionStatus,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain import pick_ban_rules as pbr  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterReadiness,
    PickBanEntry,
    PickBanSession,
)
from src.services.encounter.pick_ban_session import pick_ban_session_service  # noqa: E402
from src.services.encounter.pregame_rooms import (  # noqa: E402
    derive_attention,
    derive_phase,
    pregame_rooms_service,
)
from tests._pickban_room import map_config  # noqa: E402
from tests._pregame_store import _Store, staged_topics  # noqa: E402

TOURNAMENT = 7
HOME, AWAY = MapPickSide.HOME.value, MapPickSide.AWAY.value
MAP_TOPIC_DOMAIN = "map-veto"


def _encounter(**kwargs: object) -> Encounter:
    """An encounter with both slots filled, as the board's happy path needs."""
    fields: dict[str, object] = {
        "name": "A vs B",
        "tournament_id": TOURNAMENT,
        "stage_id": None,
        "stage_item_id": None,
        "round": 1,
        "best_of": 3,
        "home_team_id": 10,
        "away_team_id": 20,
        "home_score": 0,
        "away_score": 0,
        "status": EncounterStatus.OPEN,
        "result_status": EncounterResultStatus.NONE,
    }
    fields.update(kwargs)
    return Encounter(**fields)  # type: ignore[arg-type]


class CaptainReadySignalTests(IsolatedAsyncioTestCase):
    """``mark_ready`` is the only write in the pre-game phase before a session
    exists, so it is the only thing that can wake the opposite captain."""

    async def test_insert_signals_the_room_once(self) -> None:
        store = _Store()
        encounter = _encounter()
        store.seed(encounter)

        await pick_ban_session_service.mark_ready(store, encounter, HOME, None)

        self.assertEqual([f"encounter:{encounter.id}:{MAP_TOPIC_DOMAIN}"], staged_topics(store))

    async def test_idempotent_repeat_signals_nothing(self) -> None:
        store = _Store()
        encounter = _encounter()
        store.seed(encounter)
        store.seed(EncounterReadiness(encounter_id=encounter.id, side=HOME, ready_user_id=None))

        readiness = await pick_ban_session_service.mark_ready(store, encounter, HOME, None)

        self.assertEqual({"home": True, "away": False}, readiness)
        self.assertEqual([], staged_topics(store))


class ClearReadinessTests(IsolatedAsyncioTestCase):
    async def test_clears_one_side_and_signals(self) -> None:
        store = _Store()
        encounter = _encounter()
        store.seed(encounter)
        store.seed(
            EncounterReadiness(encounter_id=encounter.id, side=HOME, ready_user_id=None),
            EncounterReadiness(encounter_id=encounter.id, side=AWAY, ready_user_id=None),
        )

        readiness = await pick_ban_session_service.clear_ready(store, encounter, AWAY)

        self.assertEqual({"home": True, "away": False}, readiness)
        self.assertEqual([f"encounter:{encounter.id}:{MAP_TOPIC_DOMAIN}"], staged_topics(store))

    async def test_refuses_once_a_session_exists(self) -> None:
        store = _Store()
        encounter = _encounter()
        store.seed(encounter)
        store.seed(
            EncounterReadiness(encounter_id=encounter.id, side=HOME, ready_user_id=None),
            PickBanSession(
                encounter_id=encounter.id,
                kind=PickBanKind.MAP,
                config_id=None,
                status=MapVetoSessionStatus.ACTIVE,
                resolved_sequence_json=[],
            ),
        )

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.clear_ready(store, encounter, HOME)

        self.assertEqual(409, caught.exception.status_code)
        # Nothing cleared, nothing signalled: the organizer resets instead.
        self.assertEqual({"home": True, "away": False}, await pick_ban_session_service.get_readiness(store, 1))
        self.assertEqual([], staged_topics(store))


class DerivePhaseTests(TestCase):
    """The ranking, as a pure function. A room can be several things at once;
    the board shows the one that is blocking progress."""

    def _phase(self, **overrides: bool) -> str:
        facts: dict[str, bool] = {
            "teams_known": True,
            "done": False,
            "any_session": False,
            "readiness_complete": True,
            "map_open": False,
            "hero_open": False,
            "report_pending": False,
        }
        facts.update(overrides)
        return derive_phase(**facts)  # type: ignore[arg-type]

    def test_unknown_team_outranks_everything(self) -> None:
        self.assertEqual("teams_unknown", self._phase(teams_known=False, done=True, map_open=True))

    def test_done_outranks_an_open_room(self) -> None:
        self.assertEqual("done", self._phase(done=True, map_open=True, report_pending=True))

    def test_readiness_only_while_no_session_exists(self) -> None:
        self.assertEqual("readiness", self._phase(readiness_complete=False))
        # A session already open means readiness is behind us, whatever the
        # rows say (an organizer may have cleared one side's confirmation).
        self.assertEqual("map", self._phase(readiness_complete=False, any_session=True, map_open=True))

    def test_map_before_hero_before_report(self) -> None:
        self.assertEqual("map", self._phase(any_session=True, map_open=True, hero_open=True, report_pending=True))
        self.assertEqual("hero", self._phase(any_session=True, hero_open=True, report_pending=True))
        self.assertEqual("report", self._phase(any_session=True, report_pending=True))

    def test_nothing_owed_is_idle(self) -> None:
        self.assertEqual("idle", self._phase(any_session=True))


class DeriveAttentionTests(TestCase):
    def _flags(self, **overrides: object) -> list[str]:
        now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        facts: dict[str, object] = {
            "phase": "idle",
            "result_disputed": False,
            "game_disputed": False,
            "awaiting_choice": False,
            "overdue": False,
            "scheduled_at": None,
            "now": now,
        }
        facts.update(overrides)
        return derive_attention(**facts)  # type: ignore[arg-type]

    def test_quiet_room_raises_nothing(self) -> None:
        self.assertEqual([], self._flags())

    def test_every_flag_in_reading_order(self) -> None:
        self.assertEqual(
            ["game_disputed", "result_disputed", "awaiting_choice", "overdue", "late_not_ready"],
            self._flags(
                phase="readiness",
                result_disputed=True,
                game_disputed=True,
                awaiting_choice=True,
                overdue=True,
                scheduled_at=datetime(2026, 10, 2, 11, 0, tzinfo=UTC),
            ),
        )

    def test_late_not_ready_needs_both_the_phase_and_a_passed_start(self) -> None:
        past = datetime(2026, 10, 2, 11, 0, tzinfo=UTC)
        future = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)
        self.assertEqual(["late_not_ready"], self._flags(phase="readiness", scheduled_at=past))
        self.assertEqual([], self._flags(phase="readiness", scheduled_at=future))
        # A match that started late but is already picking is not "not ready".
        self.assertEqual([], self._flags(phase="map", scheduled_at=past))

    def test_naive_schedule_is_read_as_utc(self) -> None:
        self.assertEqual(["late_not_ready"], self._flags(phase="readiness", scheduled_at=datetime(2026, 10, 2, 11, 0)))


class PregameRoomsBoardTests(IsolatedAsyncioTestCase):
    """The store-backed half: the bulk reads, the row filter and the summaries
    the pure functions are fed."""

    def _store(self, *rows: object) -> _Store:
        store = _Store()
        store.seed(map_config(), *rows)
        return store

    async def _rooms(self, store: _Store) -> list:
        return (await pregame_rooms_service.list_rooms(store, TOURNAMENT)).rooms

    async def test_waiting_on_readiness_and_late(self) -> None:
        encounter = _encounter(scheduled_at=datetime.now(UTC) - timedelta(minutes=30))
        store = self._store(encounter)
        store.seed(EncounterReadiness(encounter_id=encounter.id, side=HOME, ready_user_id=None))

        rows = await self._rooms(store)

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("readiness", row.phase)
        self.assertEqual(["late_not_ready"], row.attention)
        self.assertEqual({"home": True, "away": False}, row.readiness)
        # Configured but never opened: no status, and the reason the room
        # itself would show.
        self.assertIsNone(row.map.status)
        self.assertEqual("not_ready", row.map.reason)
        # No hero config at all: not a room this encounter plays.
        self.assertIsNone(row.hero)

    async def test_reads_nothing_into_existence(self) -> None:
        """The whole point of a separate read service: unlike
        ``get_pick_ban_state`` it must not create the session it reports on."""
        encounter = _encounter()
        store = self._store(encounter)
        store.seed(
            EncounterReadiness(encounter_id=encounter.id, side=HOME, ready_user_id=None),
            EncounterReadiness(encounter_id=encounter.id, side=AWAY, ready_user_id=None),
        )

        rows = await self._rooms(store)

        self.assertEqual([], store.all_of(PickBanSession))
        self.assertEqual([], store.all_of(EncounterGame))
        self.assertEqual([], staged_topics(store))
        # Both sides ready and nothing opened yet: the room is one read away
        # from existing, which is `idle` rather than `readiness`.
        self.assertEqual("idle", rows[0].phase)

    async def test_open_map_step_past_its_deadline_is_overdue(self) -> None:
        encounter = _encounter()
        store = self._store(encounter)
        started = datetime.now(UTC) - timedelta(minutes=5)
        store.seed(
            PickBanSession(
                encounter_id=encounter.id,
                kind=PickBanKind.MAP,
                config_id=None,
                status=MapVetoSessionStatus.ACTIVE,
                current_step_started_at=started,
                resolved_sequence_json=[_step(0, sides=[HOME], timer_seconds=60), _step(1, sides=[AWAY])],
            )
        )

        row = (await self._rooms(store))[0]

        self.assertEqual("map", row.phase)
        self.assertEqual(["overdue"], row.attention)
        self.assertEqual("active", row.map.status)
        self.assertEqual(0, row.map.step_index)
        self.assertEqual(2, row.map.step_count)
        self.assertEqual("ban", row.map.step_action)
        self.assertEqual([HOME], row.map.acting_sides)
        self.assertEqual(started + timedelta(seconds=60), row.map.deadline_at)

    async def test_round_awaiting_an_opener_choice(self) -> None:
        encounter = _encounter()
        store = self._store(encounter)
        store.seed(
            PickBanSession(
                encounter_id=encounter.id,
                kind=PickBanKind.MAP,
                config_id=None,
                status=MapVetoSessionStatus.ACTIVE,
                awaiting_choice=True,
                resolved_sequence_json=[],
            )
        )

        row = (await self._rooms(store))[0]

        # No step is open while the rotation waits for a losing captain, but
        # the room is still what the organizer must unstick.
        self.assertEqual("map", row.phase)
        self.assertIsNone(row.map.step_index)
        self.assertTrue(row.map.awaiting_choice)
        self.assertEqual(["awaiting_choice"], row.attention)

    async def test_disputed_game_is_a_report_phase_room(self) -> None:
        encounter = _encounter()
        store = self._store(encounter)
        pick_ban = PickBanSession(
            encounter_id=encounter.id,
            kind=PickBanKind.MAP,
            config_id=None,
            status=MapVetoSessionStatus.COMPLETED,
            resolved_sequence_json=[],
        )
        store.seed(pick_ban)
        store.seed(
            PickBanEntry(session_id=pick_ban.id, item_id=11, round=1, status=MapPoolEntryStatus.PICKED),
            EncounterGame(encounter_id=encounter.id, position=1, state=EncounterGameState.DISPUTED, format="duel"),
            EncounterGame(encounter_id=encounter.id, position=2, state=EncounterGameState.CONFIRMED, format="duel"),
            EncounterGame(encounter_id=encounter.id, position=3, state=EncounterGameState.CANCELLED, format="duel"),
        )

        row = (await self._rooms(store))[0]

        self.assertEqual("report", row.phase)
        self.assertEqual(["game_disputed"], row.attention)
        # The cancelled position is history and is counted nowhere.
        self.assertEqual(2, row.games.total)
        self.assertEqual(1, row.games.disputed)
        self.assertEqual(1, row.games.confirmed)
        self.assertEqual(0, row.games.awaiting_result)

    async def test_finished_encounter_is_done_and_still_flags_a_disputed_series(self) -> None:
        store = self._store(
            _encounter(status=EncounterStatus.COMPLETED, result_status=EncounterResultStatus.DISPUTED, home_score=2)
        )
        encounter = store.all_of(Encounter)[0]
        store.seed(
            EncounterGame(
                encounter_id=encounter.id, position=1, state=EncounterGameState.AWAITING_RESULT, format="duel"
            )
        )

        row = (await self._rooms(store))[0]

        self.assertEqual("done", row.phase)
        self.assertEqual(["result_disputed"], row.attention)

    async def test_unconfigured_encounter_has_no_row(self) -> None:
        store = _Store()
        store.seed(_encounter())

        self.assertEqual([], await self._rooms(store))


def _step(index: int, *, sides: list[str], timer_seconds: int | None = None) -> dict:
    """One resolved step as the session stores it -- built through the engine's
    own model, so a schema change breaks here instead of silently drifting."""
    return pbr.ResolvedStep(
        index=index,
        round=1,
        phase_id="p1",
        step_id=f"s{index}",
        action="ban",
        sides=sides,
        count=1,
        min=1,
        blind=False,
        target=None,
        lifetime=None,
        timer_seconds=timer_seconds,
        on_timeout="random_fill",
        dispute=pbr.DisputeRule(),
        eligible={},
        constraints=[],
    ).to_json()
