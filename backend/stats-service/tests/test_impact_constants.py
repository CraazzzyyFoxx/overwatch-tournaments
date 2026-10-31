# backend/stats-service/tests/test_impact_constants.py
from shared.core import enums, impact, impact_weights


def test_new_log_stats_members_exist():
    for name in (
        "FirstPicks",
        "FirstDeaths",
        "UltimateKills",
        "SupportKills",
        "ImpactPoints",
        "ImpactRank",
        "OverperformanceScore",
        "OverperformanceBadge",
    ):
        assert hasattr(enums.LogStatsName, name)


def test_features_reference_real_stat_names():
    for name in impact.IMPACT_FEATURES:
        assert hasattr(enums.LogStatsName, name), name
    assert set(impact.EVENT_STATS) <= set(impact.IMPACT_FEATURES)
    assert set(impact.PRIOR_WEIGHTS) == set(impact.IMPACT_FEATURES)


def test_every_feature_has_a_contribution_stat():
    assert set(impact.CONTRIBUTION_STATS) == set(impact.IMPACT_FEATURES)
    assert len({stat.value for stat in impact.CONTRIBUTION_STATS.values()}) == len(impact.IMPACT_FEATURES)
    for feature, stat in impact.CONTRIBUTION_STATS.items():
        assert stat.name == f"Contrib{feature}"
        assert stat.value.startswith("contrib_")


def test_weights_cover_every_role_and_feature():
    assert set(impact_weights.IMPACT_WEIGHTS) == set(impact.IMPACT_ROLES)
    for role, weights in impact_weights.IMPACT_WEIGHTS.items():
        assert set(weights) == set(impact.IMPACT_FEATURES), role


def test_directions():
    assert enums.is_ascending_stat(enums.LogStatsName.FirstDeaths) is True
    assert enums.is_ascending_stat(enums.LogStatsName.ImpactRank) is True
    assert enums.is_ascending_stat(enums.LogStatsName.ImpactPoints) is False
    assert enums.is_ascending_stat(enums.LogStatsName.FirstPicks) is False
    assert enums.is_ascending_stat(enums.LogStatsName.OverperformanceBadge) is False
    assert enums.is_ascending_stat(enums.LogStatsName.ContribEliminations) is False
