"""The pre-game room's journal: what the room writes down, and what the
organizer reads back.

The write side is driven through the REAL services against
``tests/_pickban_room.Room``: a journal pinned against hand-made rows would
prove nothing about the paths that are supposed to append them. What is pinned
is the contract the organizer's journal strip depends on -- a captain's action
is attributed, the clock's is not, and a session reset does not take the story
with it (rows are keyed by ENCOUNTER exactly so that reset cannot erase them).

The read side is a merge of two tables with different shapes, so it is
exercised against stub repositories: the ordering and the result-row mapping
are the logic, and the two SQL reads behind them are one statement each.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core import enums  # noqa: E402
from shared.core.enums import PickBanKind  # noqa: E402
from shared.models.tournament.encounter_result_audit import EncounterResultAudit  # noqa: E402
from shared.models.tournament.encounter_room_event import EncounterRoomEvent  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from src.services.encounter.pick_ban_session import pick_ban_session_service  # noqa: E402
from src.services.encounter.room_journal import RoomHistoryService  # noqa: E402
from tests._pickban_room import HOME, Room, v1_ruleset  # noqa: E402

TIMED_BANS = v1_ruleset(sequence=["ban_first", "ban_second"], turn_timer_seconds=30)


def events(room: Room, action: str | None = None) -> list[EncounterRoomEvent]:
    rows = room.store.all_of(EncounterRoomEvent)
    return [row for row in rows if action is None or row.action == action]


class RoomJournalWriteTests(IsolatedAsyncioTestCase):
    async def test_a_captain_action_is_journaled_once_with_its_actor_and_side(self) -> None:
        room = Room(hero_ruleset=TIMED_BANS, hero_items=[1, 2, 3])
        await room.open(PickBanKind.HERO)

        await pick_ban_action_service.perform_pick_ban_action(
            room.store,
            room.encounter_id,
            PickBanKind.HERO,
            HOME,
            item_id=1,
            action="ban",
            actor_auth_user_id=77,
        )

        self.assertEqual(1, len(events(room, "session_opened")), "the room opened exactly once")
        acted = events(room, "acted")
        self.assertEqual(1, len(acted))
        row = acted[0]
        self.assertEqual(("captain", HOME, "hero", 77), (row.source, row.side, row.kind, row.actor_auth_user_id))
        self.assertEqual(
            {"step_index": 0, "round": 1, "action": "ban", "item_id": 1, "target_player_id": None}, row.data
        )

    async def test_a_timed_out_step_is_the_clock_s_row_not_a_person_s(self) -> None:
        room = Room(hero_ruleset=TIMED_BANS, hero_items=[1, 2, 3])
        await room.open(PickBanKind.HERO)
        room.session(PickBanKind.HERO).current_step_started_at = datetime.now(UTC) - timedelta(hours=1)

        await room.state(PickBanKind.HERO)

        timed_out = events(room, "step_timed_out")
        self.assertEqual(1, len(timed_out))
        row = timed_out[0]
        self.assertEqual("system", row.source)
        self.assertIsNone(row.actor_auth_user_id)
        self.assertIsNone(row.side, "the clock stands in for a side, it does not act as one")
        self.assertEqual([HOME], row.data["sides"])
        self.assertEqual(0, row.data["step_index"])

    async def test_a_reset_keeps_the_rows_of_the_session_it_scrapped(self) -> None:
        room = Room(hero_ruleset=TIMED_BANS, hero_items=[1, 2, 3])
        await room.act(HOME, 1, kind=PickBanKind.HERO)
        before = [row.action for row in events(room)]

        await pick_ban_session_service.reset_pick_ban_session(
            room.store, room.encounter, PickBanKind.HERO, actor_auth_user_id=5
        )

        after = [row.action for row in events(room)]
        self.assertEqual(before, after[: len(before)], "the scrapped session's story survives it")
        self.assertIn("session_reset", after)
        reset_row = events(room, "session_reset")[0]
        self.assertEqual(("admin", 5, "hero"), (reset_row.source, reset_row.actor_auth_user_id, reset_row.kind))
        self.assertEqual(2, len(events(room, "session_opened")), "the reset re-opened the room")

    async def test_a_repeated_ready_adds_nothing(self) -> None:
        room = Room(hero_ruleset=TIMED_BANS, hero_items=[1, 2, 3])
        # The fixture seeds both sides ready, so every call here is a repeat.
        await pick_ban_session_service.mark_ready(room.store, room.encounter, HOME, None, actor_auth_user_id=3)

        self.assertEqual([], events(room, "ready_marked"))


def _room_row(id: int, at: datetime, action: str, **kwargs: object) -> EncounterRoomEvent:
    kwargs.setdefault("source", "captain")
    row = EncounterRoomEvent(encounter_id=1, action=action, data={}, **kwargs)
    row.id = id
    row.created_at = at
    return row


def _result_row(id: int, at: datetime, source: str = "admin") -> EncounterResultAudit:
    row = EncounterResultAudit(
        encounter_id=1,
        action=enums.EncounterResultAuditAction.GAME_CORRECT,
        to_result_status=enums.EncounterResultStatus.CONFIRMED,
        home_score_before=0,
        away_score_before=0,
        home_score_after=2,
        away_score_after=1,
        source=source,
        reason="miscounted",
        game_id=9,
    )
    row.id = id
    row.created_at = at
    return row


class _StubRepo:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    async def list_with_actor(self, session: object, encounter_id: int, *, limit: int) -> list:
        return self.rows[:limit]


class RoomHistoryReadTests(IsolatedAsyncioTestCase):
    def _service(self, room_rows: list, result_rows: list) -> RoomHistoryService:
        return RoomHistoryService(event_repo=_StubRepo(room_rows), audit_repo=_StubRepo(result_rows))

    async def test_both_journals_merge_newest_first(self) -> None:
        base = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        service = self._service(
            [
                (_room_row(2, base + timedelta(minutes=5), "acted", side=HOME), "captain-bob"),
                (_room_row(1, base, "session_opened", source="system"), None),
            ],
            [(_result_row(4, base + timedelta(minutes=9)), "Player One", 2)],
        )

        history = await service.list_history(None, 1, limit=10)

        self.assertEqual(["result:4", "room:2", "room:1"], [entry.id for entry in history.entries])
        corrected = history.entries[0]
        self.assertEqual(("result", "game_correct", "admin"), (corrected.origin, corrected.action, corrected.source))
        self.assertEqual("Player One", corrected.actor_name)
        self.assertIsNone(corrected.actor_auth_user_id, "a result actor is a player id, not an auth one")
        self.assertEqual(2, corrected.data["position"])
        self.assertEqual((2, 1), (corrected.data["home_score"], corrected.data["away_score"]))
        self.assertEqual("confirmed", corrected.data["result_status"])

    async def test_an_unattributed_machine_source_reads_as_system(self) -> None:
        base = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        service = self._service([], [(_result_row(1, base, source="captain_agreement"), None, 1)])

        history = await service.list_history(None, 1, limit=10)

        self.assertEqual("system", history.entries[0].source)

    async def test_the_limit_is_clamped_and_applied_after_the_merge(self) -> None:
        base = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        service = self._service(
            [(_room_row(index, base + timedelta(minutes=index), "acted"), None) for index in (3, 2, 1)],
            [(_result_row(9, base + timedelta(minutes=2, seconds=30)), None, 1)],
        )

        self.assertEqual(
            ["room:3", "result:9"], [entry.id for entry in (await service.list_history(None, 1, limit=2)).entries]
        )
        # 0 is not "no rows" and 10_000 is not "everything": both clamp.
        self.assertEqual(1, len((await service.list_history(None, 1, limit=0)).entries))
        self.assertEqual(4, len((await service.list_history(None, 1, limit=10_000)).entries))
