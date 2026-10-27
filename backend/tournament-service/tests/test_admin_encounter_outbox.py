from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


admin_encounter_service = importlib.import_module("src.services.admin.encounter")
schemas = importlib.import_module("src.schemas")


def _result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    result.first.return_value = value
    result.unique.return_value = result
    result.scalars.return_value = SimpleNamespace(first=lambda: value, all=lambda: [] if value is None else [value])
    return result


def _scalars_result(values):
    scalars = Mock()
    scalars.all.return_value = values
    scalars.first.return_value = values[0] if values else None
    result = Mock()
    result.scalars.return_value = scalars
    result.unique.return_value = result
    return result


class AdminEncounterOutboxTests(IsolatedAsyncioTestCase):
    async def test_create_encounter_enqueues_recalc_before_commit(self) -> None:
        calls: list[str] = []
        execute_count = 0

        async def fake_execute(_query):
            nonlocal execute_count
            execute_count += 1
            if execute_count == 1:
                calls.append("loaded_tournament")
                return _result(SimpleNamespace(id=1, workspace_id=7, discipline="overwatch"))
            # The stage reference is validated by a query ...
            calls.append("loaded_stage")
            return _result(SimpleNamespace(id=10, scoring_rule_id=3))

        async def fake_commit():
            calls.append("commit")

        async def fake_enqueue(_session, tournament_id):
            calls.append(f"enqueue:{tournament_id}")

        session = SimpleNamespace(
            execute=AsyncMock(side_effect=fake_execute),
            # ... and its rule comes from an identity-map lookup.
            get=AsyncMock(return_value=SimpleNamespace(id=10, scoring_rule_id=3)),
            add=Mock(),
            commit=AsyncMock(side_effect=fake_commit),
            refresh=AsyncMock(),
        )
        payload = schemas.EncounterCreate(
            name="Round 1",
            tournament_id=1,
            stage_id=10,
            round=1,
        )

        with (
            patch.object(
                admin_encounter_service,
                "enqueue_tournament_recalculation",
                AsyncMock(side_effect=fake_enqueue),
            ) as enqueue_recalc,
            patch.object(admin_encounter_service.lifecycle_notifier, "on_encounter_changed", AsyncMock()),
        ):
            encounter = await admin_encounter_service.encounter_service.create_encounter(session, payload)

        # The encounter carries the owner's copies (D62) and the stage's rule.
        self.assertEqual(
            (1, 7, "overwatch", 3, 2),
            (
                encounter.tournament_id,
                encounter.workspace_id,
                encounter.discipline,
                encounter.scoring_rule_id,
                encounter.slot_count,
            ),
        )
        enqueue_recalc.assert_awaited_once_with(session, 1)
        self.assertLess(calls.index("enqueue:1"), calls.index("commit"))

    async def test_update_encounter_enqueues_recalc_before_commit(self) -> None:
        calls: list[str] = []
        encounter = SimpleNamespace(
            id=10,
            slot_count=2,
            scoring_preset="wins",
            tournament_id=1,
            scheduled_at=None,
            name="old",
            best_of=3,
            status=admin_encounter_service.enums.EncounterStatus.OPEN,
            result_status=admin_encounter_service.enums.EncounterResultStatus.NONE,
        )
        execute_results = iter([_result(encounter), _result(SimpleNamespace(id=20))])

        async def fake_commit():
            calls.append("commit")

        async def fake_enqueue(_session, tournament_id):
            calls.append(f"enqueue:{tournament_id}")

        session = SimpleNamespace(
            execute=AsyncMock(side_effect=lambda _query: next(execute_results)),
            get=AsyncMock(return_value=SimpleNamespace(stage_id=20, stage_item_id=None, round=1)),
            commit=AsyncMock(side_effect=fake_commit),
            refresh=AsyncMock(),
        )
        payload = schemas.EncounterUpdate(name="new", best_of=5)

        with patch.object(
            admin_encounter_service,
            "enqueue_tournament_recalculation",
            AsyncMock(side_effect=fake_enqueue),
        ):
            updated = await admin_encounter_service.encounter_service.update_encounter(session, encounter.id, payload)

        self.assertEqual(("new", 5), (updated.name, updated.best_of))
        self.assertEqual(calls, ["enqueue:1", "commit"])
