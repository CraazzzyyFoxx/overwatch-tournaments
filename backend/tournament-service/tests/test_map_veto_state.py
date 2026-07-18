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

from datetime import UTC, datetime  # noqa: E402

from shared.core.enums import MapPickSide, MapPoolEntryStatus, MapVetoSessionStatus  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.services.encounter.map_veto import (  # noqa: E402
    apply_veto_action,
    auto_complete_decider_entry,
    build_map_pool_state,
    build_unavailable_state,
    serialize_map_pool_entry,
    serialize_veto_session,
)


def make_pool_entry(
    map_id: int,
    *,
    status: MapPoolEntryStatus = MapPoolEntryStatus.AVAILABLE,
    order: int = 0,
    action_index: int | None = None,
    picked_by: MapPickSide | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=map_id,
        map_id=map_id,
        order=order,
        action_index=action_index,
        status=status,
        picked_by=picked_by,
    )


def make_veto_session(
    sequence: list[str],
    *,
    status: MapVetoSessionStatus = MapVetoSessionStatus.ACTIVE,
    first_side: MapPickSide = MapPickSide.HOME,
) -> SimpleNamespace:
    started = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=1,
        status=status,
        first_side=first_side,
        seed_source="bracket_slot",
        home_seed=1,
        away_seed=4,
        turn_timer_seconds=60,
        started_at=started,
        current_step_started_at=started,
        resolved_sequence_json=sequence,
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
        self.assertEqual(2, resolved.action_index)


class SerializationTests(TestCase):
    def test_pool_entry_includes_action_index(self) -> None:
        entry = make_pool_entry(7, status=MapPoolEntryStatus.BANNED, action_index=3, picked_by=MapPickSide.AWAY)

        data = serialize_map_pool_entry(entry)

        self.assertEqual(
            {"id": 7, "map_id": 7, "order": 0, "action_index": 3, "picked_by": MapPickSide.AWAY,
             "status": MapPoolEntryStatus.BANNED},
            data,
        )

    def test_veto_session_serializes_iso_datetimes(self) -> None:
        veto = make_veto_session(["ban_home", "pick_away"])

        data = serialize_veto_session(veto)

        self.assertEqual("2026-07-18T12:00:00+00:00", data["started_at"])
        self.assertEqual("2026-07-18T12:00:00+00:00", data["current_step_started_at"])
        self.assertEqual(MapVetoSessionStatus.ACTIVE, data["status"])
        self.assertEqual(1, data["home_seed"])
        self.assertEqual(4, data["away_seed"])

    def test_state_includes_sequence_and_session(self) -> None:
        veto = make_veto_session(["ban_home", "pick_away"])
        pool = [make_pool_entry(1), make_pool_entry(2), make_pool_entry(3)]

        state = build_map_pool_state(veto.resolved_sequence_json, pool, viewer_side="home", veto=veto)

        self.assertEqual(["ban_home", "pick_away"], state["sequence"])
        self.assertEqual(1, state["session"]["id"])
        self.assertEqual(MapVetoSessionStatus.ACTIVE, state["session"]["status"])

    def test_unavailable_state_shapes(self) -> None:
        for reason in ("not_configured", "teams_unknown"):
            state = build_unavailable_state(reason)
            self.assertEqual(
                {
                    "session": None,
                    "reason": reason,
                    "sequence": [],
                    "pool": [],
                    "viewer_side": None,
                    "viewer_can_act": False,
                    "allowed_actions": [],
                    "current_step_index": None,
                    "current_step": None,
                    "expected_action": None,
                    "turn_side": None,
                    "is_complete": False,
                },
                state,
            )


class ApplyVetoActionTests(TestCase):
    NOW = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)

    def test_actions_stamp_global_action_index(self) -> None:
        veto = make_veto_session(["ban_home", "ban_away", "pick_home"])
        pool = [make_pool_entry(1), make_pool_entry(2), make_pool_entry(3)]

        first = apply_veto_action(veto, pool, "home", 1, "ban", now=self.NOW)
        second = apply_veto_action(veto, pool, "away", 2, "ban", now=self.NOW)

        self.assertEqual(0, first.action_index)
        self.assertEqual(MapPoolEntryStatus.BANNED, first.status)
        self.assertEqual(MapPickSide.HOME, first.picked_by)
        self.assertEqual(1, second.action_index)
        self.assertEqual(self.NOW, veto.current_step_started_at)
        self.assertEqual(MapVetoSessionStatus.ACTIVE, veto.status)

    def test_final_step_completes_session(self) -> None:
        veto = make_veto_session(["ban_home", "pick_away"])
        pool = [
            make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            make_pool_entry(2),
            make_pool_entry(3),
        ]

        entry = apply_veto_action(veto, pool, "away", 2, "pick", now=self.NOW)

        self.assertEqual(1, entry.action_index)
        self.assertEqual(MapPoolEntryStatus.PICKED, entry.status)
        self.assertEqual(MapVetoSessionStatus.COMPLETED, veto.status)

    def test_rejects_wrong_turn(self) -> None:
        veto = make_veto_session(["ban_home", "ban_away"])
        pool = [make_pool_entry(1), make_pool_entry(2)]

        with self.assertRaises(HTTPException) as ctx:
            apply_veto_action(veto, pool, "away", 1, "ban", now=self.NOW)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertEqual("It's home team's turn, not away", ctx.exception.detail)

    def test_rejects_wrong_action_type(self) -> None:
        veto = make_veto_session(["ban_home", "pick_away"])
        pool = [make_pool_entry(1), make_pool_entry(2)]

        with self.assertRaises(HTTPException) as ctx:
            apply_veto_action(veto, pool, "home", 1, "pick", now=self.NOW)

        self.assertEqual("Expected action 'ban', got 'pick'", ctx.exception.detail)

    def test_rejects_unavailable_map(self) -> None:
        veto = make_veto_session(["ban_home", "ban_away"])
        pool = [
            make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0),
            make_pool_entry(2),
        ]

        with self.assertRaises(HTTPException) as ctx:
            apply_veto_action(veto, pool, "away", 1, "ban", now=self.NOW)

        self.assertEqual("Map is already banned", str(ctx.exception.detail))

    def test_rejects_completed_sequence(self) -> None:
        veto = make_veto_session(["ban_home"])
        pool = [make_pool_entry(1, status=MapPoolEntryStatus.BANNED, picked_by=MapPickSide.HOME, action_index=0)]

        with self.assertRaises(HTTPException) as ctx:
            apply_veto_action(veto, pool, "home", 1, "ban", now=self.NOW)

        self.assertEqual("Veto sequence is already complete", ctx.exception.detail)
