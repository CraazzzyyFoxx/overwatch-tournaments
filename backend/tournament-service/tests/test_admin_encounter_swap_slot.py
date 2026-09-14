"""Bracket slot swaps exchange team ids, rebuild both names, and refuse a
settled or live encounter.

The swap is seeding surgery: it rewires the team slots the reports, pick-ban
sessions and standings all key off. Anything past seeding (completed, disputed,
or a series already running) must be sent to the reopen endpoint instead of
being re-teamed underneath its result.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

enc_service = importlib.import_module("src.services.admin.encounter")
schemas = importlib.import_module("src.schemas")
enums = importlib.import_module("shared.core.enums")


@contextmanager
def assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - inspect status_code attribute
        test_case.assertEqual(getattr(exc, "status_code", None), expected_status)
        return
    test_case.fail(f"expected an exception with status_code {expected_status}")


def _encounter(encounter_id: int, home: int | None, away: int | None, **overrides) -> SimpleNamespace:
    fields = {
        "id": encounter_id,
        "tournament_id": 1,
        "stage_id": 5,
        "stage_item_id": 6,
        "home_team_id": home,
        "away_team_id": away,
        "name": "n/a",
        "status": enums.EncounterStatus.OPEN,
        "result_status": enums.EncounterResultStatus.NONE,
        "started_at": None,
        "ended_at": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


def _session() -> SimpleNamespace:
    return SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), add=lambda _obj: None)


@contextmanager
def _repos(*encounters: SimpleNamespace):
    """Stub the two repo reads and the two post-swap side effects.

    Teams are named after their id ("t1"), so an asserted name spells out which
    team landed in which slot.
    """
    by_id = {encounter.id: encounter for encounter in encounters}
    service = enc_service.encounter_service
    with (
        patch.object(
            service.encounter_repo,
            "get_for_update",
            AsyncMock(side_effect=lambda _s, eid, **_k: by_id.get(eid)),
        ),
        patch.object(service.team_repo, "get", AsyncMock(side_effect=lambda _s, tid: SimpleNamespace(name=f"t{tid}"))),
        patch.object(
            enc_service.pick_ban_session_service,
            "sync_all_pick_ban_sessions_after_team_change",
            AsyncMock(),
        ) as sync,
        patch.object(enc_service, "enqueue_tournament_recalculation", AsyncMock()) as enqueue,
    ):
        yield SimpleNamespace(sync=sync, enqueue=enqueue)


def _body(slot: str, target_id: int, target_slot: str):
    return schemas.EncounterSwapSlotInput(slot=slot, target_encounter_id=target_id, target_slot=target_slot)


class SwapSlots(IsolatedAsyncioTestCase):
    async def test_swaps_between_two_open_encounters(self) -> None:
        source = _encounter(10, 1, 2)
        target = _encounter(11, 3, None)
        with _repos(source, target) as stubs:
            returned_source, returned_target = await enc_service.encounter_service.swap_slots(
                _session(), 10, _body("home", 11, "away")
            )

        self.assertEqual((None, 2), (source.home_team_id, source.away_team_id))
        self.assertEqual((3, 1), (target.home_team_id, target.away_team_id))
        self.assertEqual("TBD vs t2", source.name)
        self.assertEqual("t3 vs t1", target.name)
        self.assertIs(source, returned_source)
        self.assertIs(target, returned_target)
        self.assertEqual(2, stubs.sync.await_count)
        self.assertEqual(1, stubs.enqueue.await_count)

    async def test_flips_home_and_away_within_one_encounter(self) -> None:
        encounter = _encounter(10, 1, 2)
        with _repos(encounter) as stubs:
            returned_source, returned_target = await enc_service.encounter_service.swap_slots(
                _session(), 10, _body("home", 10, "away")
            )

        self.assertEqual((2, 1), (encounter.home_team_id, encounter.away_team_id))
        self.assertEqual("t2 vs t1", encounter.name)
        self.assertIs(encounter, returned_source)
        self.assertIs(encounter, returned_target)
        # One row touched -> one pick-ban sync, not two.
        self.assertEqual(1, stubs.sync.await_count)

    async def test_rejects_the_same_slot_of_the_same_encounter(self) -> None:
        with assert_http_status(self, 400):
            await enc_service.encounter_service.swap_slots(_session(), 10, _body("home", 10, "home"))

    async def test_rejects_a_completed_target(self) -> None:
        source = _encounter(10, 1, 2)
        target = _encounter(
            11,
            3,
            4,
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
        )
        with _repos(source, target), assert_http_status(self, 409):
            await enc_service.encounter_service.swap_slots(_session(), 10, _body("home", 11, "home"))
        self.assertEqual(1, source.home_team_id)

    async def test_rejects_a_live_target(self) -> None:
        source = _encounter(10, 1, 2)
        target = _encounter(11, 3, 4, started_at=datetime.now(UTC))
        with _repos(source, target), assert_http_status(self, 409):
            await enc_service.encounter_service.swap_slots(_session(), 10, _body("home", 11, "home"))
        self.assertEqual(1, source.home_team_id)

    async def test_rejects_a_target_in_another_stage(self) -> None:
        source = _encounter(10, 1, 2)
        target = _encounter(11, 3, 4, stage_id=9)
        with _repos(source, target), assert_http_status(self, 400):
            await enc_service.encounter_service.swap_slots(_session(), 10, _body("home", 11, "home"))
        self.assertEqual(1, source.home_team_id)
