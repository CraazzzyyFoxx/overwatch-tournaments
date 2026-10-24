"""Frozen D96 evidence the P4 feature oracle does not carry: quantile execution, standings/shift prediction frames
and the predictions of real fitted fixture estimators.

``fixtures/ml_prediction_parity.json`` was captured ONCE under the pre-move P5 analytics code (``fixtures/ml_pre_move``
holds the provenance and the estimator state bundles); it is never regenerated from the code under test. The fixture
estimators are real small LightGBM / XGBoost / scikit-learn objects whose learned state is loaded from
``*.state.joblib`` (library objects and plain fields only -- no custom class); the model wrappers are rebuilt around
that state without calling ``fit``.

Everything compares bit-for-bit except the cells later fixes changed on purpose, by explicit path in ``_assert_equal``:
the reseeded pre-encounter OpenSkill mu and the rescaled Performance confidence.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import typing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sqlalchemy as sa
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.disciplines.overwatch import analytics as ow_analytics
from shared.division_grid import DEFAULT_GRID, canonical_division_number
from shared.domain.analytics import align_features
from src.core import config
from src.services.ml.features.aggregations import build_match_features_with_strength
from src.services.ml.features.shift_features import build_shift_feature_frame
from src.services.ml.features.standings_features import (
    build_standings_forecast_frame,
    build_standings_training_frame,
)
from src.services.ml.inference.match_quality_runner import _match_scores
from tests.ow_analytics import exports
from tests.ow_analytics import module as ow_module
from tests.test_stats_feature_parity import PRE_FIX_COARSE_FEATURES, _frame, native_analytics_reader  # noqa: F401

ROLE_KPIS = ow_module("features.role_kpis").ROLE_KPIS
STANDINGS_FEATURE_ORDER = ow_module("models.standings_v2").STANDINGS_FEATURE_ORDER
SHIFT_BLEND_COLUMNS = ow_module("models.shift_v2").SHIFT_BLEND_COLUMNS
COARSE_FEATURES = PRE_FIX_COARSE_FEATURES  # the order the golden and every pre-fix artifact carry
MVP_MIN_MATCHES = ow_module("features.mvp_dominance").MVP_MIN_MATCHES

# The concrete Overwatch code, reached through the registry; the three builders are the service's own.
_ow = SimpleNamespace(
    PerformanceModelV2=ow_analytics.PerformanceModelV2,
    ConstantClassifier=ow_analytics._ConstantClassifier,
    WinProbabilityModel=ow_analytics.WinProbabilityModel,
    ShiftModelV2=ow_analytics.ShiftModelV2,
    align_features=align_features,
    build_target=ow_module("models.performance_v2").build_target,
    aggregate_to_tournament=exports.aggregate_to_tournament,
    impact_score_within_role=exports.impact_score_within_role,
    stabilize_small_cohort_impact=exports.stabilize_small_cohort_impact,
    attach_local_performance=exports.attach_local_performance,
    features_for_role=exports.features_for_role,
    feature_matrix=ow_module("models.standings_v2")._feature_matrix,
    simulate_standings=exports.simulate_standings,
    train_shift_v2=exports.train_shift_v2,
    compute_match_quality=exports.compute_match_quality,
    detect_smurfs=exports.detect_smurfs,
    detect_trolls=exports.detect_trolls,
    detect_sandbags=exports.detect_sandbags,
    detect_throws=exports.detect_throws,
    build_match_features=build_match_features_with_strength,
    build_shift_frame=build_shift_feature_frame,
    build_forecast_frame=build_standings_forecast_frame,
    build_training_frame=build_standings_training_frame,
    match_scores=_match_scores,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "ml_prediction_parity.json"
STATE = FIXTURES / "ml_pre_move"
ROLES = ("tank", "damage", "support")
CASES = (
    ("primary", "tournament", "workspace"),
    ("secondary", "tournament_other", "workspace_other"),
    ("hidden", "tournament_hidden", "workspace"),
    ("wrong_workspace", "tournament", "workspace_other"),
)


# ---------------------------------------------------------------------------
# Deterministic synthetic inputs (shared by the one-off capture and every run)
# ---------------------------------------------------------------------------


def synthetic_frame(seed: int, n: int, columns: typing.Iterable[str]) -> pd.DataFrame:
    """Seeded numeric frame with NaNs, reversed column order and playtime branches."""
    rng = np.random.default_rng(seed)
    special = {"rank", "is_home", "is_newcomer", "won", "score_delta", "role"}
    names = sorted({*columns, "team_avg_mu", "opp_avg_mu", "mu_gap"} - special)
    frame = pd.DataFrame({name: rng.normal(size=n).round(6) for name in names})
    frame["rank"] = rng.integers(1, 3000, size=n)
    frame["is_home"] = rng.random(n) < 0.5
    frame["is_newcomer"] = rng.random(n) < 0.3
    frame["won"] = (rng.random(n) < 0.5).astype(int)
    frame["score_delta"] = rng.integers(-3, 4, size=n)
    frame["hero_time_played"] = rng.choice([0.0, np.nan, 300.0, 600.0, 900.0], size=n)
    frame["role"] = rng.choice(["Tank", "damage", "SUPPORT"], size=n)
    frame["player_id"] = np.arange(n)
    frame["tournament_id"] = 1
    mask = rng.random((n, len(names))) < 0.08
    frame[names] = frame[names].mask(mask)
    return frame[list(frame.columns[::-1])]


def _every_column() -> list[str]:
    columns: dict[str, None] = {}
    for kpis in ROLE_KPIS.values():
        columns.update(dict.fromkeys(kpis))
    columns.update(dict.fromkeys(COARSE_FEATURES))
    columns.update(dict.fromkeys(STANDINGS_FEATURE_ORDER))
    columns.update(dict.fromkeys(SHIFT_BLEND_COLUMNS))
    return list(columns)


def evaluation_frame() -> pd.DataFrame:
    """12 rows, some columns absent so ``align_features`` must insert NaN."""
    frame = synthetic_frame(2026, 12, _every_column())
    return frame.drop(columns=["deaths_p10", "synergy_winrate_gap"], errors="ignore")


# ---------------------------------------------------------------------------
# Probe predictors (observe the real aligned matrix, return deterministic numbers)
# ---------------------------------------------------------------------------


class _Probe:
    def __init__(self, offset: float) -> None:
        self.offset = offset
        self.inputs: list[dict] = []

    def _score(self, frame: pd.DataFrame) -> np.ndarray:
        self.inputs.append(_frame(frame))
        return np.nansum(frame.to_numpy(dtype=float), axis=1) * 0.001 + self.offset

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self._score(frame)

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        p = np.clip(self._score(frame), 0.01, 0.99)
        return np.column_stack([1 - p, p])


# ---------------------------------------------------------------------------
# Fixture model reconstruction (no fit)
# ---------------------------------------------------------------------------


def _fixture_state(name: str) -> dict:
    return joblib.load(STATE / f"{name}.state.joblib")


def _no_fit(*_a, **_k):
    raise AssertionError("fixture estimators must never be refit")


@contextlib.contextmanager
def _fit_forbidden() -> typing.Iterator[None]:
    with contextlib.ExitStack() as stack:
        for target in (lgb.LGBMRegressor, xgb.XGBClassifier, CalibratedClassifierCV, LogisticRegression, Pipeline):
            stack.enter_context(patch.object(target, "fit", _no_fit))
        yield


def load_fixture_models() -> dict[str, typing.Any]:
    models: dict[str, typing.Any] = {}
    for role in ROLES:
        state = _fixture_state(f"performance_{role}")
        kind, payload = state.pop("baseline")
        baseline = _ow.ConstantClassifier(prior=payload) if kind == "constant" else payload
        models[f"performance_{role}"] = _ow.PerformanceModelV2(baseline=baseline, **state)
    models["standings"] = _ow.WinProbabilityModel(**_fixture_state("standings"))
    for name in ("shift_default", "shift_tuned", "shift_old_missing"):
        model = object.__new__(_ow.ShiftModelV2)
        model.__dict__.update(_fixture_state(name))
        models[name] = model
    return models


# ---------------------------------------------------------------------------
# Output collection
# ---------------------------------------------------------------------------


def _role_frame(frame: pd.DataFrame, role: str) -> pd.DataFrame:
    return frame.loc[frame["role"].str.lower() == role]


def _quantile_execution(frame: pd.DataFrame) -> dict:
    """Real main/quantile/coarse dispatch with probe boosters that return numbers."""
    out = {}
    for role in sorted(frame["role"].str.lower().unique()):
        role_frame = _role_frame(frame, role)
        cases = {}
        for label, coarse_enabled in (("with_coarse", True), ("without_coarse", False)):
            main, q10, q90, coarse = _Probe(0.0), _Probe(-0.2), _Probe(0.2), _Probe(0.05)
            model = _ow.PerformanceModelV2(
                role=role,
                booster=main,
                booster_q10=q10,
                booster_q90=q90,
                feature_order=list(_ow.features_for_role(role)),
                coarse_booster=coarse if coarse_enabled else None,
                coarse_feature_order=list(COARSE_FEATURES) if coarse_enabled else [],
                shift_range=2.0,
            )
            predicted = model.predict_match(role_frame)
            cases[label] = {
                "main": main.inputs,
                "q10": q10.inputs,
                "q90": q90.inputs,
                "coarse": coarse.inputs,
                "predict_match": _frame(predicted),
                "predict": _frame(model.predict(role_frame).to_frame("y_hat")),
            }
        out[role] = cases
    return out


def _fitted_performance(models: dict, frame: pd.DataFrame) -> dict:
    """Fitted-model predictions + the runner's tournament roll-up and local/impact post-processing."""
    out: dict[str, typing.Any] = {"per_role": {}}
    y_hat = pd.Series(index=frame.index, dtype=float)
    y_q10 = pd.Series(index=frame.index, dtype=float)
    y_q90 = pd.Series(index=frame.index, dtype=float)
    for role in ROLES:
        model = models[f"performance_{role}"]
        mask = frame["role"].str.lower() == role
        if not mask.any():
            continue
        predicted = model.predict_match(frame[mask])
        out["per_role"][role] = _frame(predicted)
        y_hat.loc[mask], y_q10.loc[mask], y_q90.loc[mask] = predicted["y_hat"], predicted["y_q10"], predicted["y_q90"]
    per_player = _ow.aggregate_to_tournament(frame, y_hat, y_q10, y_q90)
    out["aggregate"] = _frame(per_player)
    if per_player.empty:
        return out
    per_player["impact_score"] = _ow.impact_score_within_role(per_player)
    ranks = frame.groupby("player_id", dropna=False)["rank"].first().to_dict()
    per_player["division"] = per_player["player_id"].map(
        lambda player_id: None
        if pd.isna(rank := ranks.get(player_id))
        else canonical_division_number(DEFAULT_GRID, int(rank), DEFAULT_GRID)
    )
    per_player = _ow.attach_local_performance(per_player)
    out["local"] = _frame(per_player)
    out["stabilized"] = _frame(_ow.stabilize_small_cohort_impact(per_player))
    return out


def _matchups(frame: pd.DataFrame, p_home: np.ndarray) -> pd.DataFrame:
    paired = frame.assign(p_home_wins=p_home).dropna(subset=["home_team_id", "away_team_id"])
    return pd.DataFrame(
        {
            "home_team_id": paired["home_team_id"].astype(int).to_numpy(),
            "away_team_id": paired["away_team_id"].astype(int).to_numpy(),
            "p_home_wins": paired["p_home_wins"].to_numpy(),
        }
    )


def _standings_outputs(models: dict, frame: pd.DataFrame) -> dict:
    out: dict[str, typing.Any] = {"frame": _frame(frame)}
    if frame.empty:
        return out
    fitted = models["standings"]
    out["feature_matrix"] = _frame(_ow.feature_matrix(frame, fitted.feature_order))
    probe = _Probe(0.5)
    probe_model = _ow.WinProbabilityModel(booster=probe, baseline=None)
    out["probe_proba"] = probe_model.predict_proba(frame).tolist()
    out["probe_input"] = probe.inputs
    p_home = fitted.predict_proba(frame)
    out["fitted_proba"] = p_home.tolist()
    out["fitted_predict"] = _frame(fitted.predict(frame).to_frame())
    matchups = _matchups(frame, p_home)
    if not matchups.empty:
        teams = sorted({int(t) for t in matchups["home_team_id"].tolist() + matchups["away_team_id"].tolist()})
        out["simulation"] = _frame(
            _ow.simulate_standings(
                matchups,
                teams,
                n_iter=300,
                rng=np.random.default_rng(20261018),
                prob_sharpening=1.5,
            )
        )
    return out


def _legacy_equivalent(frame: pd.DataFrame) -> pd.DataFrame:
    """Inputs on which the current shift blend and smurf MVP rule reproduce the frozen receipts.

    Both changed on purpose after capture: a negative ``local_zscore`` now lowers the shift, and the MVP lift and the
    smurf MVP rule need ``MVP_MIN_MATCHES`` logged matches. Clipping the z at 0 and granting the logged matches keeps the
    rest of each model comparable bit-for-bit; the unit tests cover the two changes themselves.
    """
    legacy = frame.assign(mvp_matches=MVP_MIN_MATCHES)
    if "performance_v2_local_zscore" in legacy:
        legacy["performance_v2_local_zscore"] = legacy["performance_v2_local_zscore"].clip(lower=0.0)
    return legacy


def _shift_outputs(models: dict, frame: pd.DataFrame) -> dict:
    out: dict[str, typing.Any] = {"frame": _frame(frame)}
    legacy = _legacy_equivalent(frame)
    for name in ("shift_default", "shift_tuned", "shift_old_missing"):
        model = models[name]
        out[name] = {
            "confidence": _frame(model.predict_with_uncertainty(legacy)),
            "predict": _frame(model.predict(legacy).to_frame()),
        }
    return out


def _synthetic_outputs(models: dict) -> dict:
    frame = evaluation_frame()
    out: dict[str, typing.Any] = {"input": _frame(frame), "quantile_execution": _quantile_execution(frame)}
    out["fitted_performance"] = _fitted_performance(models, frame)
    role_frame = _role_frame(frame, "damage")
    baselines = {}
    for role in ROLES:
        baseline = models[f"performance_{role}"].baseline
        baselines[role] = baseline.predict_proba(
            frame[["team_avg_mu", "opp_avg_mu", "mu_gap"]].fillna(0.0).to_numpy()
        ).tolist()
    out["baselines"] = baselines
    out["aligned_main"] = {
        role: _frame(_ow.align_features(frame, models[f"performance_{role}"].feature_order)) for role in ROLES
    }
    out["standings_fitted"] = _standings_outputs(
        models, frame.assign(home_team_id=range(12), away_team_id=range(1, 13))
    )
    out["shift"] = _shift_outputs(models, frame.assign(current_div=np.arange(12) % 7 + 1, grid_n_div=20))
    trained = _ow.train_shift_v2(
        _legacy_equivalent(
            frame.assign(current_div=np.arange(12) % 7 + 1, next_tournament_div=np.arange(12) % 5 + 1, grid_n_div=20)
        ),
        val_df=_legacy_equivalent(frame.assign(current_div=3, next_tournament_div=2, grid_n_div=20)),
        w_team=0.6,
        w_os=0.4,
        indiv_scale_top=0.25,
        indiv_scale_bottom=0.9,
        indiv_clamp_top=0.8,
        indiv_clamp_bottom=2.2,
        dominance_gain=5.5,
        dominance_cap=2.5,
        placement_floor=0.1,
        clamp_top_grid_ref=21.0,
    )
    out["train_shift"] = {
        "state": _value_dict(trained.model.__dict__),
        "metrics": trained.metrics,
        "feature_importance": trained.feature_importance,
    }
    out["role_frame_rows"] = len(role_frame)
    out["anomalies"] = _anomaly_outputs()
    return out


def _value_dict(values: dict) -> dict:
    return {key: (list(value) if isinstance(value, list) else value) for key, value in values.items()}


def _anomaly_outputs() -> dict:
    rng = np.random.default_rng(77)
    n = 16
    profile = pd.DataFrame(
        {
            "player_id": np.arange(100, 100 + n),
            "role": ["tank", "damage", "support", "damage"] * 4,
            "rank": rng.integers(1, 3000, size=n).astype(float),
            "impact_score": rng.uniform(0, 100, size=n),
            "local_zscore": rng.normal(size=n) * 1.4,
            "local_percentile": rng.uniform(0, 100, size=n),
            "kd": rng.uniform(0.3, 4.0, size=n),
            "weapon_accuracy": rng.uniform(0.2, 0.7, size=n),
            "final_blows_p10": rng.uniform(2, 20, size=n),
            "mvp_dominance": rng.uniform(0.2, 0.95, size=n),
            "confidence": rng.uniform(0.2, 1.0, size=n),
        }
    )
    profile = _legacy_equivalent(profile)
    profile["local_zscore_history"] = [
        [float(v) for v in rng.normal(loc=0.4 if i % 3 else -1.0, size=3 + i % 2).round(3)] for i in range(n)
    ]
    rounds = []
    for player, drop in ((200, True), (201, False), (202, True)):
        for encounter in (1, 2):
            series = np.concatenate([rng.normal(1.1, 0.2, 4), rng.normal(-1.3 if drop else 1.0, 0.2, 4)])
            for number, value in enumerate(series, start=1):
                rounds.append({"player_id": player, "encounter_id": encounter, "round": number, "y_perf": float(value)})
    residuals = pd.DataFrame(rounds)
    settings = config.settings
    return {
        "smurf_defaults": _ow.detect_smurfs(profile),
        "smurf_settings": _ow.detect_smurfs(
            profile,
            strong_local_z_threshold=settings.smurf_strong_local_z,
            mvp_dominance_threshold=settings.smurf_mvp_dominance,
        ),
        "trolls": _ow.detect_trolls(profile),
        "sandbags": _ow.detect_sandbags(profile),
        "throws": _ow.detect_throws(residuals),
    }


async def _database_outputs(session: AsyncSession, ids: dict[str, int], models: dict) -> dict:
    out: dict[str, typing.Any] = {}
    # A cross-database feature-cache hit is not evidence from this SQL fixture.
    with patch.object(config.settings, "analytics_feature_cache_enabled", False):
        for case, tournament, workspace in CASES:
            tid, wid = ids[tournament], ids[workspace]
            enriched = await _ow.build_match_features(session, tid, discipline="overwatch", workspace_id=wid)
            entry: dict[str, typing.Any] = {"enriched": _frame(enriched)}
            if not enriched.empty:
                replayed = _with_frozen(enriched, _golden()["database"][case]["enriched"], _MU_REDUCTION_COLUMNS)
                entry["quantile_execution"] = _quantile_execution(replayed)
                entry["fitted_performance"] = _fitted_performance(models, replayed)
            forecast = await _ow.build_forecast_frame(session, tid, discipline="overwatch", workspace_id=wid)
            entry["forecast"] = _standings_outputs(models, forecast)
            training = await _ow.build_training_frame(session, [tid], discipline="overwatch", workspace_id=wid)
            entry["training"] = _standings_outputs(models, training)
            if not training.empty:
                encounters = training.copy()
                encounters["p_home_wins"] = models["standings"].predict_proba(encounters)
                scores = await _ow.match_scores(session, tid, discipline="overwatch")
                entry["match_quality"] = {
                    "scores": _frame(scores),
                    "default": _frame(_ow.compute_match_quality(encounters, scores)),
                    "explicit": _frame(
                        _ow.compute_match_quality(
                            encounters,
                            scores,
                            competitiveness_weight=0.2,
                            predictability_weight=0.5,
                            skill_balance_weight=0.3,
                            sigma_pool=2.5,
                        )
                    ),
                }
            shift = await _ow.build_shift_frame(session, [tid], discipline="overwatch", workspace_id=wid)
            if shift.empty:
                entry["shift"] = {"frame": _frame(shift)}
            else:
                frozen = _golden()["database"][case]["shift"]["frame"]
                outputs = _shift_outputs(models, _with_frozen(shift, frozen, _LINEAR_REDESIGNED))
                entry["shift"] = {**outputs, "frame": _frame(shift)}
            out[case] = entry
    return out


async def collect_outputs(session: AsyncSession, ids: dict[str, int], models: dict) -> dict:
    return {"synthetic": _synthetic_outputs(models), "database": await _database_outputs(session, ids, models)}


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


# The pre-encounter mu replay now starts from the seed ratings, not the post-replay ones (an outcome leak), and the v1
# Linear history was redesigned (restart at a division change, map weights): those live cells of the database enriched
# and shift frames are not comparable to the frozen ones. The models are replayed on the frozen values
# (``_with_frozen``), so everything they compute from a database frame still compares bit-for-bit.
_MU_REDUCTION_COLUMNS = frozenset(
    {"team_avg_mu", "team_max_mu", "team_min_mu", "opp_avg_mu", "opp_max_mu", "opp_min_mu", "mu_gap"}
)
_LINEAR_REDESIGNED = frozenset(
    {
        "linear_stable_shift",
        "linear_trend_shift",
        "linear_effective_evidence",
        "linear_sample_tournaments",
        "linear_sample_matches",
    }
)
# The shift frame's heuristic v1 confidences were replaced by posterior sds.
_SHIFT_FRAME_REMOVED = {"linear_confidence", "confidence_v1"}
_SHIFT_FRAME_ADDED = {"linear_shift_sd", "os_shift_sd"}
# Performance confidence is rescaled to the target's own band (spread / 2, was / 4) and is 0 for a coarse-fallback
# match, which no longer carries the fake ``y_hat -/+ 0.25`` quantile band.
_COARSE_BAND = {"y_q10": -0.25, "y_q90": 0.25}


@functools.cache
def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _with_frozen(frame: pd.DataFrame, golden: dict, columns: frozenset[str]) -> pd.DataFrame:
    """``frame`` carrying the golden's values for ``columns``."""
    frozen = pd.DataFrame(golden["rows"], columns=golden["columns"], index=frame.index)
    return frame.assign(**{column: frozen[column].astype(frame[column].dtype) for column in columns & set(frozen)})


def _is_frame(value: typing.Any) -> bool:
    return isinstance(value, dict) and {"columns", "dtypes", "index", "rows"} <= value.keys()


def _changed_columns(path: tuple) -> frozenset[str]:
    """Cells of a database frame that later fixes changed on purpose (see ``_MU_REDUCTION_COLUMNS``)."""
    if not path or path[0] != "database":
        return frozenset()
    names = [part for part in path if isinstance(part, str)]
    if names[-1] == "enriched":
        return _MU_REDUCTION_COLUMNS
    if names[-2:] == ["shift", "frame"]:
        return _MU_REDUCTION_COLUMNS | _LINEAR_REDESIGNED
    return frozenset()


def _project(frame: dict, columns: list[str]) -> dict:
    keep = [frame["columns"].index(column) for column in columns]
    return {
        **frame,
        "columns": columns,
        "column_axis": {**frame["column_axis"], "values": columns},
        "dtypes": [frame["dtypes"][i] for i in keep],
        "rows": [[row[i] for i in keep] for row in frame["rows"]],
    }


def _shift_column(frame: dict) -> dict:
    """The ``shift_v2`` column of a shift uncertainty frame: the heuristic v1 ``confidence`` it stood beside is gone."""
    keep = frame["columns"].index("shift_v2")
    return {
        "dtype": frame["dtypes"][keep],
        "index": frame["index"],
        "rows": [row[keep] for row in frame["rows"]],
    }


def _assert_equal(actual: typing.Any, expected: typing.Any, path: tuple = ()) -> None:
    assert type(actual) is type(expected), path
    if _is_frame(expected) and path[-1:] == ("confidence",) and "shift" in path:
        # ``predict_with_uncertainty`` replaced ``predict_with_confidence``: its ``shift_sd`` has no frozen counterpart.
        _assert_equal(_shift_column(actual), _shift_column(expected), path)
    elif _is_frame(expected):
        changed = _changed_columns(path)
        if _SHIFT_FRAME_REMOVED <= set(expected["columns"]):
            assert set(expected["columns"]) - set(actual["columns"]) == _SHIFT_FRAME_REMOVED, path
            assert set(actual["columns"]) - set(expected["columns"]) == _SHIFT_FRAME_ADDED, path
            shared = [column for column in expected["columns"] if column in actual["columns"]]
            actual, expected = _project(actual, shared), _project(expected, shared)
        assert actual.keys() == expected.keys(), path
        for key in expected.keys() - {"rows"}:
            _assert_equal(actual[key], expected[key], (*path, key))
        assert len(actual["rows"]) == len(expected["rows"]), path
        performance = "quantile_execution" in path or "fitted_performance" in path
        for number, (row, old_row) in enumerate(zip(actual["rows"], expected["rows"], strict=True)):
            assert len(row) == len(old_row) == len(expected["columns"]), path
            for column, value, old_value in zip(expected["columns"], row, old_row, strict=True):
                cell = (*path, "rows", number, column)
                if column in changed or (performance and column == "confidence"):
                    continue
                if performance and column in _COARSE_BAND and value is None and old_value is not None:
                    old_y_hat = old_row[expected["columns"].index("y_hat")]
                    assert old_value == old_y_hat + _COARSE_BAND[column], cell
                    continue
                _assert_equal(value, old_value, cell)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key in expected:
            _assert_equal(actual[key], expected[key], (*path, key))
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (value, old_value) in enumerate(zip(actual, expected, strict=True)):
            _assert_equal(value, old_value, (*path, index))
    else:
        assert actual == expected, path


def _to_json(value: typing.Any) -> typing.Any:
    return json.loads(json.dumps(value, allow_nan=False))


def test_ml_prediction_parity(native_analytics_reader) -> None:  # noqa: F811
    asyncio.run(_ml_prediction_parity(native_analytics_reader))


async def _ml_prediction_parity(native_analytics_reader) -> None:  # noqa: F811
    url, ids, role = native_analytics_reader
    models = load_fixture_models()
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            await session.execute(sa.text(f'SET LOCAL ROLE "{role}"'))
            with _fit_forbidden():
                actual = _to_json(await collect_outputs(session, ids, models))
    finally:
        await engine.dispose()
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _assert_equal(actual["synthetic"], expected["synthetic"], ("synthetic",))
    _assert_equal(actual["database"], expected["database"], ("database",))


def test_fixture_set_is_complete_and_old_shift_state_lacks_later_fields() -> None:
    """A shift state pickled before the tuning fields existed must load and degrade to the class defaults."""
    assert set(load_fixture_models()) == {
        "performance_tank",
        "performance_damage",
        "performance_support",
        "standings",
        "shift_default",
        "shift_tuned",
        "shift_old_missing",
    }
    state = _fixture_state("shift_old_missing")
    assert "indiv_scale_top" not in state and "clamp_top_grid_ref" not in state


def test_foreign_discipline_rows_do_not_change_overwatch_outputs(stats_parity_database) -> None:
    """A same-workspace LoL tournament with a same-code ``damage`` descendant role must leave every Overwatch frame,
    quantile input and prediction exactly as frozen."""
    from shared.testing.stats_parity import seed_native_sentinel

    url, ids = stats_parity_database
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            seed_native_sentinel(conn, ids)
    finally:
        engine.dispose()
    models = load_fixture_models()

    async def run() -> dict:
        async_engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(async_engine) as session:
                with _fit_forbidden():
                    return _to_json(await _database_outputs(session, ids, models))
        finally:
            await async_engine.dispose()

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _assert_equal(asyncio.run(run()), expected["database"], ("database",))
