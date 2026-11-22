"""``Workspace.achievement_eval_mode`` decides which automatic achievement events run."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))

from shared.models.achievements.achievement import AchievementEvalMode as Mode  # noqa: E402
from src.services.achievement.engine.consumer import plan_evaluation  # noqa: E402

TABLES = ["stats.fact"]


@pytest.mark.parametrize("reason", ["data_changed", "stage_completed", "tournament_finished"])
@pytest.mark.parametrize("finished", [False, True])
def test_manual_never_runs(reason, finished):
    assert plan_evaluation(Mode.manual, reason, TABLES, finished) == (False, None)


def test_live_runs_every_change_but_skips_the_redundant_stage_completion():
    assert plan_evaluation(Mode.live, "data_changed", TABLES, False) == (True, TABLES)
    assert plan_evaluation(Mode.live, "tournament_finished", TABLES, True) == (True, TABLES)
    assert plan_evaluation(Mode.live, "stage_completed", [], False) == (False, [])


def test_stage_end_waits_for_a_completion_then_runs_every_rule():
    assert plan_evaluation(Mode.stage_end, "data_changed", TABLES, False) == (False, TABLES)
    assert plan_evaluation(Mode.stage_end, "stage_completed", [], False) == (True, None)
    assert plan_evaluation(Mode.stage_end, "tournament_finished", TABLES, True) == (True, None)


def test_stage_end_runs_late_changes_of_a_finished_tournament_at_once():
    assert plan_evaluation(Mode.stage_end, "data_changed", TABLES, True) == (True, TABLES)
