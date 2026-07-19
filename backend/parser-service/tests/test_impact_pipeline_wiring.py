from __future__ import annotations

import inspect
import os
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

# ``src.services.match_logs.flows`` imports ``src.core.config.settings`` at
# module load, which reads these from the environment (see test_match_log_parser).
os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.core.impact import IMPACT_WEIGHTS  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.match_logs import impact  # noqa: E402
from src.services.match_logs.flows import MatchLogProcessor  # noqa: E402


def test_create_stats_accepts_kill_feed():
    sig = inspect.signature(MatchLogProcessor.create_stats)
    assert "kill_feed" in sig.parameters


def test_impact_context_shape():
    ctx = impact.ImpactContext(players={}, baselines=None, has_killfeed=False)
    assert ctx.baselines is None


# ---------------------------------------------------------------------------
# DB-free integration coverage of the impact-scoring block inside
# ``_calculate_and_add_derived_stats`` (the load-bearing logic Task 5 wired
# up). No DB/session is needed: the method only reads/writes a pandas pivot
# and calls the static ``_create_stat_object`` helper, so a bare
# ``MatchLogProcessor.__new__`` instance is sufficient to drive it.
# ---------------------------------------------------------------------------


def _fake_match() -> types.SimpleNamespace:
    return types.SimpleNamespace(id=1)


def _fake_player_model(player_id: int, user_id: int, team_id: int) -> types.SimpleNamespace:
    """Stand-in for ``models.Player`` exposing only what ``_create_stat_object``
    reads (``.team_id`` and ``.workspace_member.player_id``)."""
    return types.SimpleNamespace(
        id=player_id,
        team_id=team_id,
        role=enums.HeroClass.damage,
        rank=800,
        workspace_member=types.SimpleNamespace(player_id=user_id),
    )


def _impact_pivot_df(p1: types.SimpleNamespace, p2: types.SimpleNamespace) -> pd.DataFrame:
    """Two-player, single-round synthetic pivot with just the columns
    ``_calculate_and_add_derived_stats``/``add_impact_scores`` read."""
    rows = [
        {
            "player_id": 1,
            "player_model": p1,
            "round": 1,
            "hero_id": None,
            enums.LogStatsName.Eliminations: 20.0,
            enums.LogStatsName.Deaths: 5.0,
            enums.LogStatsName.HeroTimePlayed: 600.0,
            enums.LogStatsName.FirstPicks: 3.0,
            enums.LogStatsName.FirstDeaths: 0.0,
            enums.LogStatsName.UltimateKills: 0.0,
            enums.LogStatsName.SupportKills: 0.0,
        },
        {
            "player_id": 2,
            "player_model": p2,
            "round": 1,
            "hero_id": None,
            enums.LogStatsName.Eliminations: 5.0,
            enums.LogStatsName.Deaths: 10.0,
            enums.LogStatsName.HeroTimePlayed: 600.0,
            enums.LogStatsName.FirstPicks: 0.0,
            enums.LogStatsName.FirstDeaths: 0.0,
            enums.LogStatsName.UltimateKills: 0.0,
            enums.LogStatsName.SupportKills: 0.0,
        },
    ]
    return pd.DataFrame(rows)


def _baselines() -> impact.BaselineSet:
    """Mirrors ``test_impact_scoring.TestAddImpactScores._baselines`` so the
    resulting scores are known-good, previously-verified numbers."""
    return impact.BaselineSet(
        formula_version="impact_v1",
        bucket_bounds=(500.0, 1000.0),
        values={
            ("damage", -1, "Eliminations"): (10.0, 5.0),
            ("damage", -1, "FirstPicks"): (1.0, 1.0),
            ("damage", 1, "Eliminations"): (12.0, 5.0),
            ("damage", 1, "FirstPicks"): (1.5, 1.0),
        },
    )


def _players_map() -> dict[int, impact.PlayerRef]:
    return {
        1: impact.PlayerRef(player_id=1, user_id=101, team_id=10, role=enums.HeroClass.damage, rank=800),
        2: impact.PlayerRef(player_id=2, user_id=102, team_id=20, role=enums.HeroClass.damage, rank=800),
    }


def _stats_named(stats: list, name: enums.LogStatsName) -> list:
    return [s for s in stats if s.name == name]


def _run_derived_stats(*, baselines: impact.BaselineSet | None) -> list:
    proc = MatchLogProcessor.__new__(MatchLogProcessor)
    p1 = _fake_player_model(player_id=1, user_id=101, team_id=10)
    p2 = _fake_player_model(player_id=2, user_id=102, team_id=20)
    ctx = impact.ImpactContext(players=_players_map(), baselines=baselines, has_killfeed=True)
    return proc._calculate_and_add_derived_stats(
        _fake_match(), _impact_pivot_df(p1, p2), is_mvp_calc=True, impact_ctx=ctx
    )


def test_impact_scores_and_rank_are_emitted_and_ranked_by_impact_points():
    stats = _run_derived_stats(baselines=_baselines())

    impact_points = _stats_named(stats, enums.LogStatsName.ImpactPoints)
    assert len(impact_points) == 2
    by_user = {s.user_id: s.value for s in impact_points}
    # Eliminations rate 20/10min -> z=2.0 (w=1.3); FirstPicks rate 3 -> z=2.0 (w=0.55)
    assert by_user[101] == pytest.approx(IMPACT_WEIGHTS["Eliminations"] * 2.0 + IMPACT_WEIGHTS["FirstPicks"] * 2.0)
    # Eliminations rate 5 -> z=-1.0; FirstPicks rate 0 -> z=-1.0
    assert by_user[102] == pytest.approx(IMPACT_WEIGHTS["Eliminations"] * -1.0 + IMPACT_WEIGHTS["FirstPicks"] * -1.0)

    overperformance = _stats_named(stats, enums.LogStatsName.OverperformanceScore)
    assert len(overperformance) == 2
    overperf_by_user = {s.user_id: s.value for s in overperformance}
    # rank bucket 1: Eliminations z=(20-12)/5=1.6, FirstPicks z=(3-1.5)/1=1.5
    assert overperf_by_user[101] == pytest.approx(
        IMPACT_WEIGHTS["Eliminations"] * 1.6 + IMPACT_WEIGHTS["FirstPicks"] * 1.5
    )
    # rank bucket 1: Eliminations z=(5-12)/5=-1.4, FirstPicks z=(0-1.5)/1=-1.5
    assert overperf_by_user[102] == pytest.approx(
        IMPACT_WEIGHTS["Eliminations"] * -1.4 + IMPACT_WEIGHTS["FirstPicks"] * -1.5
    )

    ranks = _stats_named(stats, enums.LogStatsName.ImpactRank)
    assert len(ranks) == 2
    rank_by_user = {s.user_id: s.value for s in ranks}
    assert rank_by_user[101] == 1  # higher ImpactPoints -> rank 1 (MVP)
    assert rank_by_user[102] == 2


def test_baselines_none_skips_impact_but_keeps_performance():
    stats = _run_derived_stats(baselines=None)

    assert _stats_named(stats, enums.LogStatsName.ImpactPoints) == []
    assert _stats_named(stats, enums.LogStatsName.OverperformanceScore) == []
    assert _stats_named(stats, enums.LogStatsName.ImpactRank) == []

    # Performance ranking/points are computed before the impact block and
    # must not be affected by the graceful baselines-missing skip.
    assert len(_stats_named(stats, enums.LogStatsName.PerformancePoints)) == 2
    assert len(_stats_named(stats, enums.LogStatsName.Performance)) == 2
