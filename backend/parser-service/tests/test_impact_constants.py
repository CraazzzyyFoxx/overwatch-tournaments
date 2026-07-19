# backend/parser-service/tests/test_impact_constants.py
from shared.core import enums, impact


def test_new_log_stats_members_exist():
    for name in (
        "FirstPicks",
        "FirstDeaths",
        "UltimateKills",
        "SupportKills",
        "ImpactPoints",
        "ImpactRank",
        "OverperformanceScore",
    ):
        assert hasattr(enums.LogStatsName, name)


def test_weights_reference_real_stat_names():
    for key in impact.IMPACT_WEIGHTS:
        assert hasattr(enums.LogStatsName, key), key
    assert set(impact.EVENT_STATS) <= set(impact.IMPACT_WEIGHTS)


def test_directions():
    assert enums.is_ascending_stat(enums.LogStatsName.FirstDeaths) is True
    assert enums.is_ascending_stat(enums.LogStatsName.ImpactRank) is True
    assert enums.is_ascending_stat(enums.LogStatsName.ImpactPoints) is False
    assert enums.is_ascending_stat(enums.LogStatsName.FirstPicks) is False
