from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

from shared.core.enums import MapPickSide, MapPoolEntryStatus  # noqa: E402

from src.services.encounter.map_veto import (  # noqa: E402
    auto_complete_decider_entry,
    build_map_pool_state,
)


def make_pool_entry(
    map_id: int,
    *,
    status: MapPoolEntryStatus = MapPoolEntryStatus.AVAILABLE,
    order: int = 0,
    picked_by: MapPickSide | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=map_id,
        map_id=map_id,
        order=order,
        status=status,
        picked_by=picked_by,
    )


class BuildMapPoolStateTests(TestCase):
    def test_home_viewer_can_only_ban_on_home_ban_step(self) -> None:
        pool = [
            make_pool_entry(1, order=0),
            make_pool_entry(2, order=1),
            make_pool_entry(3, order=2),
        ]

        state = build_map_pool_state(["ban_home", "pick_away"], pool, viewer_side="home")

        self.assertEqual("ban_home", state["current_step"])
        self.assertEqual("ban", state["expected_action"])
        self.assertEqual("home", state["turn_side"])
        self.assertEqual(["ban"], state["allowed_actions"])
        self.assertTrue(state["viewer_can_act"])
        self.assertFalse(state["is_complete"])

    def test_other_viewer_cannot_act_when_not_their_turn(self) -> None:
        pool = [
            make_pool_entry(1, order=0),
            make_pool_entry(2, order=1),
            make_pool_entry(3, order=2),
        ]

        state = build_map_pool_state(["ban_home", "pick_away"], pool, viewer_side="away")

        self.assertEqual("home", state["turn_side"])
        self.assertEqual([], state["allowed_actions"])
        self.assertFalse(state["viewer_can_act"])

    def test_away_viewer_can_only_pick_on_away_pick_step(self) -> None:
        pool = [
            make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME),
            make_pool_entry(2, order=1),
            make_pool_entry(3, order=2),
        ]

        state = build_map_pool_state(["ban_home", "pick_away"], pool, viewer_side="away")

        self.assertEqual("pick_away", state["current_step"])
        self.assertEqual("pick", state["expected_action"])
        self.assertEqual("away", state["turn_side"])
        self.assertEqual(["pick"], state["allowed_actions"])
        self.assertTrue(state["viewer_can_act"])

    def test_decider_step_is_not_actionable_by_viewer(self) -> None:
        pool = [
            make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME),
            make_pool_entry(2, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.AWAY),
            make_pool_entry(3, order=2),
        ]

        state = build_map_pool_state(["ban_home", "pick_away", "decider"], pool, viewer_side="home")

        self.assertEqual("decider", state["current_step"])
        self.assertEqual("decider", state["expected_action"])
        self.assertIsNone(state["turn_side"])
        self.assertEqual([], state["allowed_actions"])
        self.assertFalse(state["viewer_can_act"])

    def test_complete_sequence_reports_no_pending_step(self) -> None:
        pool = [
            make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME),
            make_pool_entry(2, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.AWAY),
        ]

        state = build_map_pool_state(["ban_home", "pick_away"], pool, viewer_side="away")

        self.assertIsNone(state["current_step"])
        self.assertIsNone(state["expected_action"])
        self.assertIsNone(state["turn_side"])
        self.assertEqual([], state["allowed_actions"])
        self.assertTrue(state["is_complete"])


class AutoCompleteDeciderEntryTests(TestCase):
    def test_marks_last_available_map_as_decider_pick(self) -> None:
        pool = [
            make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, order=0),
            make_pool_entry(2, status=MapPoolEntryStatus.PICKED, picked_by=MapPickSide.AWAY, order=1),
            make_pool_entry(3, status=MapPoolEntryStatus.AVAILABLE, order=2),
        ]

        resolved = auto_complete_decider_entry(["ban_home", "pick_away", "decider"], pool)

        self.assertIsNotNone(resolved)
        self.assertEqual(MapPoolEntryStatus.PICKED, resolved.status)
        self.assertEqual(MapPickSide.DECIDER, resolved.picked_by)
        self.assertEqual(2, resolved.order)
