from __future__ import annotations

import pandas as pd

from shared.core import enums
from shared.core.impact import CONTRIBUTION_STATS, EVENT_STATS
from shared.disciplines.overwatch.backfill import BackfillService
from shared.disciplines.overwatch.impact_backfill import NEW_STAT_MEMBERS


def test_the_derived_codes_are_the_event_counts_and_every_impact_fact():
    assert set(NEW_STAT_MEMBERS) == {
        *(enums.LogStatsName[name] for name in EVENT_STATS),
        enums.LogStatsName.ImpactPoints,
        enums.LogStatsName.ImpactRank,
        enums.LogStatsName.OverperformanceScore,
        enums.LogStatsName.OverperformanceBadge,
        *CONTRIBUTION_STATS.values(),
    }
    assert len(NEW_STAT_MEMBERS) == len(set(NEW_STAT_MEMBERS))


def _events() -> pd.DataFrame:
    # Per-hero counts as ``build_event_counts`` returns them: two heroes of member 1 in round 1.
    return pd.DataFrame(
        [
            {
                "player_id": 1,
                "segment": 1,
                "hero": 10,
                "FirstPicks": 1,
                "FirstDeaths": 0,
                "UltimateKills": 0,
                "SupportKills": 1,
            },
            {
                "player_id": 1,
                "segment": 1,
                "hero": 11,
                "FirstPicks": 0,
                "FirstDeaths": 1,
                "UltimateKills": 2,
                "SupportKills": 0,
            },
            {
                "player_id": 1,
                "segment": 2,
                "hero": 10,
                "FirstPicks": 1,
                "FirstDeaths": 0,
                "UltimateKills": 0,
                "SupportKills": 0,
            },
        ]
    )


def _raw(*cells: tuple[int, int, int | None]) -> pd.DataFrame:
    return pd.DataFrame(
        [(member, segment, hero, "Eliminations", 1.0) for member, segment, hero in cells],
        columns=["player_id", "segment", "hero", "name", "value"],
    )


def _by_key(facts):
    return {(member, segment, stat.name): value for member, segment, stat, value in facts}


def test_event_facts_are_written_per_round_and_total_for_every_hero_less_segment():
    stat_rows = _raw((1, 1, None), (1, 2, None), (1, 0, None), (2, 1, None), (2, 0, None), (1, 1, 10))
    facts = _by_key(BackfillService._event_facts(stat_rows, _events()))
    assert len(facts) == 5 * len(EVENT_STATS)  # (1,1) (1,2) (1,0) (2,1) (2,0); the per-hero row opens nothing
    assert facts[(1, 1, "UltimateKills")] == 2.0 and facts[(1, 1, "FirstPicks")] == 1.0
    assert facts[(1, 0, "FirstPicks")] == 2.0 and facts[(1, 0, "SupportKills")] == 1.0
    assert facts[(2, 1, "FirstPicks")] == 0.0 and facts[(2, 0, "FirstDeaths")] == 0.0  # no event: dense zeros


def test_event_facts_without_a_kill_feed_are_all_zero():
    facts = BackfillService._event_facts(_raw((1, 1, None), (1, 0, None)), pd.DataFrame())
    assert len(facts) == 2 * len(EVENT_STATS) and {value for *_, value in facts} == {0.0}
