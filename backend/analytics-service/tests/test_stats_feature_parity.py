"""Frozen-P3 feature oracle and native D96 predictor-input parity.

Capture runs this same callable with production imports resolved to frozen P3.
Only Main writes the golden. No fitted artifact is supplied: predictor-boundary
probes stop inference after receiving the real aligned matrix, without returning
predictions or fitting a model.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models
from shared.disciplines.overwatch.analytics import PerformanceModelV2
from src.core import config
from src.services.analytics.read_queries import analytics_read_service
from src.services.analytics.service import analytics_service
from src.services.ml.features.aggregations import build_match_features_with_strength
from src.services.ml.inference.match_quality_runner import _match_scores
from tests.ow_analytics import exports as ow
from tests.ow_analytics import module as ow_module

RATE_COLUMNS = ow_module("features.extractors").RATE_COLUMNS
compute_mvp_dominance = ow.compute_mvp_dominance
extract_encounter_features = ow.extract_encounter_features
extract_match_features = ow.extract_match_features
extract_round_residuals = ow.extract_round_residuals
extract_tournament_features = ow.extract_tournament_features
features_for_role = ow.features_for_role
load_player_signal_profile = ow.load_player_signal_profile

GOLDEN = Path(__file__).parent / "fixtures" / "stats_feature_parity.json"
# The coarse order the golden captured, which every artifact trained before the label-leak fix still stores; the live
# ``COARSE_FEATURES`` dropped the outcome columns (``won`` and the scores).
PRE_FIX_COARSE_FEATURES = [
    "won", "home_score", "away_score", "score_delta", "mu_gap",
    "opp_avg_mu", "team_avg_mu", "is_home", "rank", "is_newcomer",
]  # fmt: skip


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return _value(value.value)
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return _value(value.item())
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("infinite feature values cannot be silently normalized")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("feature timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _axis(index: pd.Index) -> dict:
    result = {
        "class": type(index).__name__,
        "dtype": str(index.dtype),
        "names": _value(list(index.names)),
        "values": _value(index.tolist()),
    }
    if isinstance(index, pd.RangeIndex):
        result["range"] = [index.start, index.stop, index.step]
    if isinstance(index, pd.MultiIndex):
        result["levels"] = [_axis(level) for level in index.levels]
        result["codes"] = [code.tolist() for code in index.codes]
    return result


def _frame(frame: pd.DataFrame) -> dict:
    """Keep axes, column order, dtypes, nested histories and row/index pairing."""
    return {
        "columns": _value(frame.columns.tolist()),
        "column_axis": _axis(frame.columns),
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "index": _axis(frame.index),
        "rows": [_value(list(row)) for row in frame.itertuples(index=False, name=None)],
    }


class InputsCaptured(Exception):
    """Stop precisely at the predictor boundary; never fabricate predictions."""


class _PredictorBoundary:
    def __init__(self) -> None:
        self.inputs: list[dict] = []

    def predict(self, frame: pd.DataFrame) -> None:
        self.inputs.append(_frame(frame))
        raise InputsCaptured


def _predictor_inputs(frame: pd.DataFrame) -> dict:
    """Run the real dispatch/alignment, observing only the predictor boundary."""
    assert not frame.empty, "shared fixture must exercise actual predictor inputs"
    assert frame["hero_time_played"].isna().any(), "missing usable playtime case absent"
    assert frame["hero_time_played"].eq(0).any(), "zero usable playtime case absent"
    assert frame["hero_time_played"].gt(0).any(), "main predictor case absent"
    captures = {}
    for role in sorted(frame["role"].str.lower().unique()):
        role_frame = frame.loc[frame["role"].str.lower() == role]
        has_logs = role_frame["hero_time_played"].fillna(0).gt(0)
        branches = {}
        for branch, selected in (("main", role_frame.loc[has_logs]), ("coarse", role_frame.loc[~has_logs])):
            if selected.empty:
                continue
            main, coarse, quantile = _PredictorBoundary(), _PredictorBoundary(), _PredictorBoundary()
            model = PerformanceModelV2(
                role=role,
                booster=main,
                booster_q10=quantile,
                booster_q90=quantile,
                feature_order=list(features_for_role(role)),
                coarse_booster=coarse,
                coarse_feature_order=list(PRE_FIX_COARSE_FEATURES),
            )
            try:
                model.predict_match(selected)
            except InputsCaptured:
                pass
            else:
                raise AssertionError(f"{role}/{branch} did not reach a predictor")
            boundary, other = (main, coarse) if branch == "main" else (coarse, main)
            assert len(boundary.inputs) == 1 and not other.inputs and not quantile.inputs
            branches[branch] = {"source": _frame(selected), "aligned": boundary.inputs[0]}
        captures[role] = branches
    assert any("main" in branches for branches in captures.values())
    assert any("coarse" in branches for branches in captures.values())
    return captures


async def collect_outputs(session: AsyncSession, ids: dict[str, int]) -> dict:
    """Collect all six real families and real main/coarse aligned matrices."""
    tournaments = [ids[key] for key in ("tournament", "tournament_other", "tournament_hidden")]
    scopes = {
        "primary": {"workspace_id": ids["workspace"]},
        "secondary": {"workspace_id": ids["workspace_other"]},
        "combined": {"workspace_ids": [ids["workspace"], ids["workspace_other"]]},
    }
    outputs = {}
    for name, extractor in (
        ("match", extract_match_features),
        ("tournament", extract_tournament_features),
        ("encounter", extract_encounter_features),
    ):
        outputs[name] = {
            scope: _frame(await extractor(session, tournaments, **kwargs)) for scope, kwargs in scopes.items()
        }
        outputs[name]["empty"] = _frame(await extractor(session, [], workspace_id=ids["workspace"]))
        outputs[name]["wrong_workspace"] = _frame(
            await extractor(session, [ids["tournament"]], workspace_id=ids["workspace_other"])
        )
    outputs["round"] = {}
    outputs["dominance"] = {}
    outputs["profile"] = {}
    for case, tournament, workspace in (
        ("primary", "tournament", "workspace"),
        ("secondary", "tournament_other", "workspace_other"),
        ("hidden", "tournament_hidden", "workspace"),
    ):
        outputs["round"][case] = _frame(
            await extract_round_residuals(session, ids[tournament], workspace_id=ids[workspace])
        )
        outputs["dominance"][case] = _frame(await compute_mvp_dominance(session, ids[tournament]))
        outputs["profile"][case] = _frame(
            await load_player_signal_profile(session, ids[tournament], workspace_id=ids[workspace])
        )
    outputs["round"]["wrong_workspace"] = _frame(
        await extract_round_residuals(session, ids["tournament"], workspace_id=ids["workspace_other"])
    )
    outputs["profile"]["wrong_workspace"] = _frame(
        await load_player_signal_profile(session, ids["tournament"], workspace_id=ids["workspace_other"])
    )
    for family in ("match", "tournament", "encounter", "round", "dominance", "profile"):
        assert outputs[family]["primary"]["rows"], f"shared fixture does not exercise {family}"

    # A cross-database feature-cache hit is not evidence from this SQL fixture.
    with patch.object(config.settings, "analytics_feature_cache_enabled", False):
        enriched = await build_match_features_with_strength(
            session, ids["tournament"], discipline="overwatch", workspace_id=ids["workspace"]
        )
    reversed_rows = enriched.loc[enriched["match_id"] == ids["match_reversed"]]
    assert not reversed_rows.empty, "reversed observation fixture is required"
    assert reversed_rows["home_team_id"].eq(ids["team_away"]).all()
    assert reversed_rows["away_team_id"].eq(ids["team_home"]).all()
    assert reversed_rows["is_home"].equals(reversed_rows["team_id"].eq(ids["team_away"]))
    outputs["enriched"] = _frame(enriched)
    outputs["predictor_inputs"] = _predictor_inputs(enriched)
    return outputs


# Only these outputs contain floating reductions; identities, scores, orientation,
# input/raw stats, feature order and missingness never receive approximate equality.
_REDUCTIONS = {
    "tournament": {
        *(f"{column}_p10" for column in RATE_COLUMNS),
        "weapon_accuracy",
        "critical_hit_accuracy",
        "scoped_accuracy",
        "scoped_critical_hit_accuracy",
        "ult_economy",
        "performance_points",
        "performance",
        "kd",
        "kda",
        "log_coverage",
        "hero_time_played_total",
    },
    "encounter": {"home_avg_rank", "away_avg_rank", "home_std_rank", "away_std_rank", "rank_gap"},
    "round": {"y_perf"},
    "dominance": {"mvp_dominance"},
    "profile": {"kd", "weapon_accuracy", "final_blows_p10", "mvp_dominance"},
}
# The pre-encounter mu replay now starts from the seed ratings instead of the post-replay ones (an outcome leak), so the
# frozen mu cells of the enriched frame and of the inputs carrying it are no longer comparable.
_RESEEDED_MU = {"team_avg_mu", "team_max_mu", "team_min_mu", "opp_avg_mu", "opp_max_mu", "opp_min_mu", "mu_gap"}
_RESEEDED = {"enriched": _RESEEDED_MU, "predictor_inputs": _RESEEDED_MU}
# The profile history window is now the latest tournaments by start date, not an id range (ids are not chronological):
# it reaches tournaments the frozen id window missed, which stays its chronologically latest part.
_CHRONOLOGICAL_HISTORY = {"profile": {"raw_value_history", "local_residual_history", "local_zscore_history"}}


def _assert_equal(actual: Any, expected: Any, path: tuple = ()) -> None:
    assert type(actual) is type(expected), path
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        if {"columns", "dtypes", "index", "rows"}.issubset(expected):
            for key in expected.keys() - {"rows"}:
                _assert_equal(actual[key], expected[key], (*path, key))
            assert len(actual["rows"]) == len(expected["rows"]), path
            reductions = _REDUCTIONS.get(path[0], set())
            for row_number, (row, old_row) in enumerate(zip(actual["rows"], expected["rows"], strict=True)):
                assert len(row) == len(old_row) == len(expected["columns"]), path
                for column, value, old_value in zip(expected["columns"], row, old_row, strict=True):
                    cell = (*path, "rows", row_number, column)
                    if column in _RESEEDED.get(path[0], ()):
                        continue
                    if column in _CHRONOLOGICAL_HISTORY.get(path[0], ()):
                        assert type(value) is list and len(value) >= len(old_value), cell
                        _assert_equal(value[len(value) - len(old_value) :], old_value, cell)
                        continue
                    if column in reductions and type(value) is float and type(old_value) is float:
                        assert math.isclose(value, old_value, rel_tol=0.0, abs_tol=1e-12), cell
                    else:
                        _assert_equal(value, old_value, cell)
            return
        for key in expected:
            _assert_equal(actual[key], expected[key], (*path, key))
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (value, old_value) in enumerate(zip(actual, expected, strict=True)):
            _assert_equal(value, old_value, (*path, index))
    else:
        assert actual == expected, path


@pytest.fixture
def native_analytics_reader(stats_parity_database):
    """A genuine non-owner reader role, granted only the native schemas."""
    url, ids = stats_parity_database
    engine = sa.create_engine(url)
    role = f"p4_analytics_{uuid4().hex}"
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOINHERIT'))
            conn.execute(
                sa.text(f'GRANT USAGE ON SCHEMA public, tournament, encounter, stats, catalog, analytics TO "{role}"')
            )
            conn.execute(
                sa.text(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA public, tournament, encounter, stats, catalog, analytics "
                    f'TO "{role}"'
                )
            )
        yield url, ids, role
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP OWNED BY "{role}"'))
            conn.execute(sa.text(f'DROP ROLE "{role}"'))
        engine.dispose()


def test_stats_feature_parity(native_analytics_reader) -> None:
    asyncio.run(_stats_feature_parity(native_analytics_reader))


async def _stats_feature_parity(native_analytics_reader) -> None:
    url, ids, role = native_analytics_reader
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            await session.execute(sa.text(f'SET LOCAL ROLE "{role}"'))
            actual = await collect_outputs(session, ids)
    finally:
        await engine.dispose()
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _assert_equal(actual, expected)


def test_native_scores_roster_attribution_and_analytics_reads(stats_parity_database) -> None:
    asyncio.run(_native_scores_roster_attribution_and_analytics_reads(stats_parity_database))


async def _native_scores_roster_attribution_and_analytics_reads(stats_parity_database) -> None:
    url, ids = stats_parity_database
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            # Observed roles must not replace the registration inputs used by trained models.
            await session.execute(
                sa.update(models.StatsMatchPlayer)
                .where(
                    models.StatsMatchPlayer.workspace_member_id == ids["member"],
                )
                .values(observed_role_id=ids["role_support"])
            )
            frame = await extract_match_features(session, [ids["tournament"]], workspace_id=ids["workspace"])
            player = frame.loc[frame["player_id"] == ids["roster_player"]]
            assert player["role"].eq("damage").all()
            assert player["rank"].eq(3500).all()
            assert set(frame["user_id"]) == {ids["player"], ids["player_away"], ids["player_removed"]}
            assert ids["player_event_only"] not in set(frame["user_id"])
            scores = await _match_scores(session, ids["tournament"], discipline="overwatch")
            assert list(zip(scores["home_score"], scores["away_score"], strict=True)) == [
                (2, 1),
                (3, 4),
                (1, 0),
                (1, 2),
                (1, 2),
                (1, 2),
                (1, 2),
            ]
            assert str(scores["home_score"].dtype) == str(scores["away_score"].dtype) == "int64"
            rows = await analytics_service.get_analytics(session, workspace_id=ids["workspace"], discipline="overwatch")
            row = next(row for row in rows if row["player_id"] == ids["roster_player"])
            assert row["user_id"] == ids["player"] and row["rank"] == 3500 and row["role"] == "damage"
            assert math.isclose(row["performance_points"], 50.00078333333333, rel_tol=0, abs_tol=1e-12)
            assert not any(row["tournament_id"] == ids["tournament_other"] for row in rows)
            # Postgres sums bigint counts to numeric; Decimal broke ``compute_points_shifts`` (Decimal / float).
            assert all(type(r["wins"]) is int and type(r["losses"]) is int for r in rows)
            await session.execute(
                sa.insert(models.AnalyticsPlayerAnomaly).values(
                    tournament_id=ids["tournament"],
                    player_id=ids["roster_player"],
                    kind="smurf",
                    score=0.9,
                    confidence=0.8,
                    reasons=["native"],
                    source_encounter_id=None,
                )
            )
            anomalies = await analytics_read_service.get_match_quality_anomalies(session, ids["tournament"], 0)
            assert len(anomalies) == 1
            encounter_id, values = anomalies[0]
            assert encounter_id == ids["encounter"]
            assert values[0]["player_id"] == ids["roster_player"]
            assert values[0]["score"] == 0.9 and values[0]["reasons"] == ["native"]
    finally:
        await engine.dispose()
