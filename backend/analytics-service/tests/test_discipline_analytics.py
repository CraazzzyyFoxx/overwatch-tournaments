"""The discipline analytics seam: lazy registry export, the typed contract and the module-owned column construction."""

from __future__ import annotations

import dataclasses
import inspect
import subprocess
import sys
import typing
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from shared.disciplines import DISCIPLINES, discipline
from shared.disciplines.analytics import AnalyticsExports
from shared.domain.analytics import align_features
from src.core.analytics_exports import UnsupportedAnalytics, analytics_exports, assert_unique_algorithm_names
from tests.ow_analytics import exports, module


def test_registry_import_loads_no_analytics_dependency() -> None:
    """Importing the registry (what every other service does) must not pull pandas, estimators or ``src``."""
    code = (
        "import sys\n"
        "import shared.disciplines as d\n"
        "assert d.discipline('overwatch').analytics is not None\n"
        "heavy = [m for m in ('pandas', 'numpy', 'sklearn', 'lightgbm', 'xgboost', 'openskill', 'src') if m in sys.modules]\n"
        "assert not heavy, heavy\n"
        "assert 'shared.disciplines.overwatch.analytics' not in sys.modules\n"
        "d.discipline('overwatch').analytics()\n"
        "assert 'shared.disciplines.overwatch.analytics' in sys.modules\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_the_exports_object_is_the_package_module_itself() -> None:
    assert discipline("overwatch").analytics() is exports
    assert inspect.ismodule(exports) and exports.__name__ == "shared.disciplines.overwatch.analytics"


def test_a_game_without_analytics_is_unsupported_never_overwatch() -> None:
    assert DISCIPLINES["lol"].analytics is None
    with pytest.raises(UnsupportedAnalytics):
        analytics_exports("lol")
    with pytest.raises(UnsupportedAnalytics):
        analytics_exports("a-code-nobody-wrote")
    assert analytics_exports("overwatch") is exports


def test_analytics_algorithm_names_are_unique_across_disciplines() -> None:
    """A second module reusing a declared algorithm name would share its registry rows and role-less artifacts."""
    assert_unique_algorithm_names(DISCIPLINES.values())
    twin = dataclasses.replace(DISCIPLINES["lol"], code="twin", analytics=lambda: exports)
    with pytest.raises(ValueError, match="declared by both 'overwatch' and 'twin'"):
        assert_unique_algorithm_names([*DISCIPLINES.values(), twin])


def _declared_members() -> dict[str, typing.Any]:
    """Methods by name, plus the plain attributes (annotation-only) the contract lists."""
    members = {name: member for name, member in vars(AnalyticsExports).items() if inspect.isfunction(member)}
    members.update(dict.fromkeys(AnalyticsExports.__annotations__))
    return members


def test_every_contract_callable_is_a_real_export_with_the_declared_parameters() -> None:
    """The type-only contract cannot drift from the definitions it describes."""
    checked = 0
    for name, member in _declared_members().items():
        assert hasattr(exports, name), name
        if not inspect.isfunction(member):
            continue
        actual = getattr(exports, name)
        assert inspect.iscoroutinefunction(actual) == inspect.iscoroutinefunction(member), name
        declared = list(inspect.signature(member).parameters.values())[1:]  # drop ``self``
        real = list(inspect.signature(actual).parameters.values())
        assert [(p.name, p.kind) for p in declared] == [(p.name, p.kind) for p in real], name
        for want, have in zip(declared, real, strict=True):
            if want.default is not inspect.Parameter.empty and want.default is not Ellipsis:
                assert want.default == have.default, (name, want.name)
        checked += 1
    assert checked >= 30


def test_model_declarations_keep_the_registered_names_and_versions() -> None:
    assert {kind: (m.algorithm_name, m.model_version) for kind, m in exports.MODELS.items()} == {
        "performance": ("Performance ML v2", "2.0.0"),
        "shift": ("OpenSkill + ML", "2.0.0"),
        "standings": ("Standings MC v2", "2.2.0"),
        "match_quality": ("Match Quality v1", "1.0.0"),
    }
    assert exports.INFERENCE_KINDS == ("performance", "player_anomalies", "shift", "standings", "match_quality")
    from src.services.ml import FEATURE_VERSION

    assert FEATURE_VERSION == "v1.6"


@pytest.mark.parametrize("role", ["tank", "Damage", "SUPPORT"])
def test_features_for_role_resolves_the_trained_lists(role: str) -> None:
    assert exports.features_for_role(role) == module("features.role_kpis").ROLE_KPIS[role.lower()]


@pytest.mark.parametrize("role", ["jungle", "flex", "", "top"])
def test_an_unknown_role_is_rejected_rather_than_given_the_damage_model(role: str) -> None:
    with pytest.raises(ValueError, match="no Overwatch trained-feature list"):
        exports.features_for_role(role)


def test_align_features_preserves_the_index_adds_nan_and_drops_extras() -> None:
    frame = pd.DataFrame({"b": [1.0, 2.0], "extra": [9, 9]}, index=[7, 5])
    aligned = align_features(frame, ["a", "b"])
    assert list(aligned.index) == [7, 5] and list(aligned.columns) == ["a", "b"]
    assert aligned["a"].isna().all() and aligned["b"].tolist() == [1.0, 2.0]


def _rated(*roles_and_mu: tuple[str, float | None]) -> tuple[list[SimpleNamespace], dict[str, SimpleNamespace]]:
    players, ratings = [], {}
    for index, (role, mu) in enumerate(roles_and_mu):
        player = SimpleNamespace(role=role, key=f"p{index}")
        players.append(player)
        if mu is not None:
            ratings[player.key] = SimpleNamespace(mu=mu)
    return players, ratings


def test_team_strength_summary_keeps_nan_roles_population_std_and_roster_weighting() -> None:
    players, ratings = _rated(("tank", 20.0), ("damage", 24.0), ("damage", 30.0), ("support", None), ("support", 26.0))
    unrated = [SimpleNamespace(role="tank", key="unrated")]
    teams = [
        SimpleNamespace(id=1, players=players),
        SimpleNamespace(id=2, players=unrated),
        SimpleNamespace(id=3, players=_rated(("support", 25.0))[0]),
    ]
    only_support = {"p0": SimpleNamespace(mu=25.0)}

    frame = exports.summarize_team_strength(teams[:1], ratings, rating_key=lambda player: player.key)
    row = frame.iloc[0]
    assert list(frame.columns) == [
        "team_id", "avg_mu", "max_mu", "min_mu", "std_mu", "tank_mu", "damage_mu", "support_mu",
    ]  # fmt: skip
    assert (
        row["team_id"] == 1 and row["avg_mu"] == pytest.approx(25.0) and row["max_mu"] == 30.0 and row["min_mu"] == 20.0
    )
    assert row["std_mu"] == pytest.approx(float(np.std([20.0, 24.0, 30.0, 26.0])))  # ddof=0
    assert row["tank_mu"] == 20.0 and row["damage_mu"] == pytest.approx(27.0) and row["support_mu"] == 26.0

    lone = exports.summarize_team_strength([teams[2]], only_support, rating_key=lambda player: "p0")
    assert lone.iloc[0]["std_mu"] == 0.0 and np.isnan(lone.iloc[0]["tank_mu"]) and np.isnan(lone.iloc[0]["damage_mu"])

    assert exports.summarize_team_strength([teams[1]], ratings, rating_key=lambda player: player.key).empty
    nothing = exports.summarize_team_strength([], {}, rating_key=lambda player: player.key)
    assert nothing.empty and list(nothing.columns) == list(frame.columns)


def test_encounter_strength_joins_own_and_opponent_snapshots_by_source_side() -> None:
    matches = pd.DataFrame(
        {
            "encounter_id": [1, 1],
            "team_id": [10, 20],
            "home_team_id": [10, 10],
            "away_team_id": [20, 20],
            "is_home": [True, False],
        }
    )
    snapshots = pd.DataFrame(
        {
            "encounter_id": [1, 1],
            "team_id": [10, 20],
            "avg_mu": [30.0, 25.0],
            "max_mu": [32.0, 27.0],
            "min_mu": [28.0, 23.0],
            "std_mu": [1.0, 1.0],
        }
    )
    merged = exports.attach_encounter_strength(matches.copy(), snapshots)
    assert merged["team_avg_mu"].tolist() == [30.0, 25.0]
    assert merged["opp_avg_mu"].tolist() == [25.0, 30.0]
    assert merged["mu_gap"].tolist() == [5.0, -5.0]

    bare = exports.attach_encounter_strength(matches.copy(), snapshots.iloc[0:0])
    assert bare[["team_avg_mu", "opp_avg_mu", "opp_max_mu", "opp_min_mu", "mu_gap"]].isna().all().all()
    assert exports.attach_encounter_strength(pd.DataFrame(), snapshots).empty


def test_tournament_strength_averages_match_mu_and_is_nan_without_matches() -> None:
    tournament = pd.DataFrame({"tournament_id": [1, 1], "player_id": [5, 6]})
    matches = pd.DataFrame(
        {
            "tournament_id": [1, 1, 1],
            "player_id": [5, 5, 6],
            "team_avg_mu": [10.0, 20.0, 5.0],
            "opp_avg_mu": [1.0, 3.0, 2.0],
            "mu_gap": [9.0, 17.0, 3.0],
        }
    )
    out = exports.attach_tournament_strength(tournament.copy(), matches)
    assert out["team_avg_mu"].tolist() == [15.0, 5.0] and out["mu_gap"].tolist() == [13.0, 3.0]
    empty = exports.attach_tournament_strength(tournament.copy(), matches.iloc[0:0])
    assert empty[["team_avg_mu", "opp_avg_mu", "mu_gap"]].isna().all().all()


def test_the_coarse_fallback_reads_no_match_outcome() -> None:
    """The Performance target is ``won - P(win)``: an outcome column among the coarse inputs leaks the label."""
    assert not {"won", "home_score", "away_score", "score_delta"} & set(exports.COARSE_FEATURES)


class _ScaledBooster:
    def __init__(self, scale: float) -> None:
        self.scale = scale

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.scale * frame["x"].to_numpy(dtype=float)


def test_performance_confidence_spans_the_target_band_and_is_zero_without_one() -> None:
    """The target lies in (-1, 1), so a q10..q90 band of 0..2 maps to confidence 1..0; the coarse fallback has none."""
    model = exports.PerformanceModelV2(
        role="tank",
        booster=_ScaledBooster(0.0),
        booster_q10=_ScaledBooster(-1.0),
        booster_q90=_ScaledBooster(1.0),
        feature_order=["x"],
        coarse_booster=_ScaledBooster(0.1),
        coarse_feature_order=["x"],
    )
    frame = pd.DataFrame(
        {
            "x": [0.0, 0.5, 1.0, 0.3],
            "hero_time_played": [600.0, 600.0, 600.0, 0.0],
            "tournament_id": 1,
            "player_id": [1, 2, 3, 4],
            "role": "tank",
        }
    )

    predicted = model.predict_match(frame)
    per_player = exports.aggregate_to_tournament(frame, predicted["y_hat"], predicted["y_q10"], predicted["y_q90"])

    assert predicted["confidence"].tolist() == [1.0, 0.5, 0.0, 0.0]
    assert per_player.set_index("player_id")["confidence"].to_dict() == {1: 1.0, 2: 0.5, 3: 0.0, 4: 0.0}
