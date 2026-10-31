from __future__ import annotations

import pandas as pd
import pytest

from shared import models
from shared.core import enums
from shared.core.impact import IMPACT_FEATURES, SHRINK_MINUTES
from shared.disciplines.overwatch import impact
from shared.disciplines.overwatch.enums import AbilityEvent

TANK = enums.HeroClass.tank
DAMAGE = enums.HeroClass.damage
SUPPORT = enums.HeroClass.support
L = enums.LogStatsName

#: hero 4 is a damage hero with its own baseline; hero 9 has no class.
HERO_TYPES = {1: DAMAGE, 2: SUPPORT, 3: TANK, 4: DAMAGE}
WEIGHTS = {
    "damage": {"Eliminations": 1.0, "FirstPicks": 1.0},
    "support": {"Eliminations": 1.0},
    "tank": {"Eliminations": 1.0},
}


def _kill(time=0.0, rnd=1, fight=1, killer=10, victim=20, killer_hero=1, victim_hero=2, ability=None, env=False):
    return models.StatsEvent(
        match_id=1,
        t=time,
        segment=rnd,
        type_id=1,
        actor_member_id=killer + 1000,
        actor_team_id=1,
        entity_id=killer_hero,
        target_member_id=victim + 1000,
        target_team_id=2,
        related_entity_id=victim_hero,
        data={
            "fight": fight,
            "ability": ability.value if ability else None,
            "damage": 100.0,
            "is_critical_hit": False,
            "is_environmental": env,
        },
    )


MEMBER_USERS = {1010: 10, 1020: 20}


def _stints(*rows: dict) -> pd.DataFrame:
    """Stint rows: ``player_id``, ``hero``, ``seconds`` (+ ``segment`` default 0, feature counts default 0)."""
    out = []
    for row in rows:
        stint = {"segment": 0, **dict.fromkeys(IMPACT_FEATURES, 0.0), **row}
        stint["role"] = HERO_TYPES[stint["hero"]].name if stint["hero"] in HERO_TYPES else None
        out.append(stint)
    return pd.DataFrame(out)


STATS = {
    ("damage", None, "Eliminations"): (10.0, 5.0),
    ("damage", 4, "Eliminations"): (20.0, 5.0),
    ("support", None, "Eliminations"): (10.0, 5.0),
    ("tank", None, "Eliminations"): (10.0, 5.0),
}


def _baselines(**overrides) -> impact.BaselineSet:
    fields = {
        "formula_version": "impact_v2",
        "stats": STATS,
        "role_scale": {"damage": (0.0, 1.0), "support": (0.0, 1.0), "tank": (0.0, 1.0)},
        "expectation": {("damage", 2): (0.5, 1.0), ("damage", -1): (0.0, 2.0)},
        "badge_threshold": 1.0,
    }
    return impact.BaselineSet(**{**fields, **overrides})


def _facts(stints, baselines=None, *, killfeed=True, roles=None, quintiles=None) -> dict:
    out = impact.score_match(
        stints,
        baselines or _baselines(),
        WEIGHTS,
        has_killfeed=killfeed,
        roles=roles if roles is not None else impact.dominant_roles(stints[stints["segment"] == 0]),
        quintiles=quintiles or {},
    )
    return {(int(r.player_id), int(r.segment), r.stat): r.value for r in out.itertuples(index=False)}


def _factor(seconds: float, longest: float) -> float:
    minutes = seconds / 60.0
    return seconds / longest * minutes / (minutes + SHRINK_MINUTES)


class TestAssignFights:
    def test_new_fight_on_gap_and_round_change(self):
        feed = [_kill(time=1.0), _kill(time=5.0), _kill(time=25.0), _kill(time=30.0, rnd=2), _kill(time=31.0, rnd=2)]
        impact.assign_fights(feed)
        assert [k.data["fight"] for k in feed] == [1, 1, 2, 3, 3]

    def test_orders_by_time_before_assigning(self):
        later, earlier = _kill(time=30.0), _kill(time=1.0)
        impact.assign_fights([later, earlier])
        assert earlier.data["fight"] == 1 and later.data["fight"] == 2

    def test_fight_assignment_replaces_json_without_changing_event_body(self):
        kill = _kill(fight=99, env=True)
        original = kill.data
        impact.assign_fights([kill])
        assert kill.data == {**original, "fight": 1} and original["fight"] == 99


class TestBuildEventCounts:
    def _counts(self, feed):
        df = impact.build_event_counts(feed, HERO_TYPES, member_user_ids=MEMBER_USERS)
        return {(r.player_id, r.hero): r for r in df.itertuples(index=False)}

    def test_first_pick_on_killer_hero_and_first_death_on_victim_hero(self):
        rows = self._counts([_kill(time=1.0, killer_hero=4, victim_hero=2), _kill(time=3.0, killer=20, victim=10)])
        assert rows[(10, 4)].FirstPicks == 1 and rows[(10, 4)].FirstDeaths == 0
        assert rows[(20, 2)].FirstDeaths == 1 and rows[(20, 2)].FirstPicks == 0

    def test_self_kill_is_a_first_death_only(self):
        rows = self._counts([_kill(killer=10, victim=10, killer_hero=1, victim_hero=1)])
        assert rows[(10, 1)].FirstPicks == 0 and rows[(10, 1)].FirstDeaths == 1

    def test_ultimate_and_support_kills_follow_the_victim_class(self):
        rows = self._counts(
            [
                _kill(time=1.0, victim_hero=2, ability=AbilityEvent.Ultimate),
                _kill(time=2.0, victim_hero=3),  # tank victim
            ]
        )
        assert rows[(10, 1)].UltimateKills == 1 and rows[(10, 1)].SupportKills == 1

    def test_empty_feed_returns_empty_frame(self):
        assert impact.build_event_counts([], HERO_TYPES, member_user_ids=MEMBER_USERS).empty


class TestBuildStints:
    def test_map_event_counts_sum_rounds_and_unplayed_heroes_drop(self):
        stat_rows = pd.DataFrame(
            [
                (10, 1, 1, "HeroTimePlayed", 120.0),
                (10, 2, 1, "HeroTimePlayed", 180.0),
                (10, 0, 1, "HeroTimePlayed", 300.0),
                (10, 0, 1, "Eliminations", 7.0),
                (10, 0, None, "Eliminations", 7.0),  # all-heroes row: ignored
            ],
            columns=["player_id", "segment", "hero", "name", "value"],
        )
        events = pd.DataFrame(
            [
                {
                    "player_id": 10,
                    "segment": 1,
                    "hero": 1,
                    "FirstPicks": 1,
                    "FirstDeaths": 0,
                    "UltimateKills": 0,
                    "SupportKills": 0,
                },
                {
                    "player_id": 10,
                    "segment": 2,
                    "hero": 1,
                    "FirstPicks": 2,
                    "FirstDeaths": 1,
                    "UltimateKills": 0,
                    "SupportKills": 0,
                },
                {
                    "player_id": 10,
                    "segment": 2,
                    "hero": 3,
                    "FirstPicks": 5,
                    "FirstDeaths": 0,
                    "UltimateKills": 0,
                    "SupportKills": 0,
                },
            ]
        )
        stints = impact.build_stints(stat_rows, events, HERO_TYPES).set_index(["segment", "hero"])
        assert stints.loc[(0, 1), "FirstPicks"] == 3 and stints.loc[(0, 1), "FirstDeaths"] == 1
        assert stints.loc[(0, 1), "Eliminations"] == 7.0 and stints.loc[(0, 1), "role"] == "damage"
        assert (2, 3) not in stints.index  # kills on a hero without playtime are dropped

    def test_unclassed_hero_has_no_role(self):
        stat_rows = pd.DataFrame(
            [(10, 0, 9, "HeroTimePlayed", 300.0)], columns=["player_id", "segment", "hero", "name", "value"]
        )
        empty = impact.build_event_counts([], HERO_TYPES, member_user_ids={})
        assert impact.build_stints(stat_rows, empty, HERO_TYPES)["role"].iat[0] is None


class TestScoreMatch:
    def test_hero_baseline_wins_over_role_baseline(self):
        facts = _facts(
            _stints(
                {"player_id": 1, "hero": 4, "seconds": 600.0, "Eliminations": 20.0},
                {"player_id": 2, "hero": 1, "seconds": 600.0, "Eliminations": 20.0},
            )
        )
        factor = _factor(600.0, 600.0)
        assert facts[(1, 0, L.ImpactPoints)] == pytest.approx(0.0)  # z vs hero 4 (20, 5)
        assert facts[(2, 0, L.ImpactPoints)] == pytest.approx(2.0 * factor)  # z vs role (10, 5)

    def test_time_share_and_shrinkage_scale_quality(self):
        facts = _facts(
            _stints(
                {"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 20.0},
                {"player_id": 2, "hero": 1, "seconds": 300.0, "Eliminations": 10.0},
            )
        )
        assert facts[(2, 0, L.ImpactPoints)] == pytest.approx(2.0 * _factor(300.0, 600.0))

    def test_unscored_player_has_no_facts_and_takes_no_place(self):
        facts = _facts(
            _stints(
                {"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 5.0},
                {"player_id": 2, "hero": 1, "seconds": 30.0, "Eliminations": 30.0},
                {"player_id": 3, "hero": 9, "seconds": 600.0, "Eliminations": 30.0},
            )
        )
        assert {player for player, _, _ in facts} == {1}
        assert facts[(1, 0, L.ImpactRank)] == 1.0

    def test_ties_share_a_place(self):
        facts = _facts(
            _stints(
                {"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 20.0},
                {"player_id": 2, "hero": 1, "seconds": 600.0, "Eliminations": 20.0},
                {"player_id": 3, "hero": 1, "seconds": 600.0, "Eliminations": 10.0},
            )
        )
        assert [facts[(p, 0, L.ImpactRank)] for p in (1, 2, 3)] == [1.0, 1.0, 3.0]

    def test_event_features_count_only_with_a_kill_feed(self):
        stints = _stints({"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 10.0, "FirstPicks": 3.0})
        baselines = _baselines(stats={**STATS, ("damage", None, "FirstPicks"): (1.0, 1.0)})
        factor = _factor(600.0, 600.0)
        assert _facts(stints, baselines)[(1, 0, L.ImpactPoints)] == pytest.approx(2.0 * factor)
        assert _facts(stints, baselines, killfeed=False)[(1, 0, L.ImpactPoints)] == pytest.approx(0.0)

    def test_role_scale_standardises_the_composite(self):
        stints = _stints({"player_id": 1, "hero": 2, "seconds": 600.0, "Eliminations": 20.0})
        scaled = _baselines(role_scale={"support": (1.0, 4.0)})
        assert _facts(stints, scaled)[(1, 0, L.ImpactPoints)] == pytest.approx((2.0 - 1.0) / 4.0 * _factor(600, 600))

    def test_overperformance_needs_a_quintile_and_falls_back_to_the_role_expectation(self):
        stints = _stints({"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 20.0})
        factor = _factor(600.0, 600.0)
        assert (1, 0, L.OverperformanceScore) not in _facts(stints)
        cell = _facts(stints, quintiles={1: 2})[(1, 0, L.OverperformanceScore)]
        fallback = _facts(stints, quintiles={1: 4})[(1, 0, L.OverperformanceScore)]
        assert cell == pytest.approx(factor * (2.0 - 0.5) / 1.0)
        assert fallback == pytest.approx(factor * (2.0 - 0.0) / 2.0)

    def test_badge_goes_to_the_top_overperformer_past_the_threshold(self):
        stints = _stints(
            {"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 25.0},
            {"player_id": 2, "hero": 1, "seconds": 600.0, "Eliminations": 15.0},
            {"player_id": 3, "hero": 1, "seconds": 600.0, "Eliminations": 30.0},  # best, but no quintile
        )
        quintiles = {1: 2, 2: 2}
        facts = _facts(stints, quintiles=quintiles)
        assert facts[(1, 0, L.OverperformanceBadge)] == 1.0
        assert facts[(2, 0, L.OverperformanceBadge)] == 0.0
        assert (3, 0, L.OverperformanceBadge) not in facts
        out_of_reach = _facts(stints, _baselines(badge_threshold=100.0), quintiles=quintiles)
        assert out_of_reach[(1, 0, L.OverperformanceBadge)] == 0.0

    def test_contributions_add_up_to_impact_plus_the_role_offset(self):
        stints = _stints({"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 20.0, "FirstPicks": 3.0})
        baselines = _baselines(role_scale={"damage": (1.0, 2.0)})
        facts = _facts(stints, baselines)
        contributions = sum(v for (_, _, stat), v in facts.items() if stat.value.startswith("contrib_"))
        offset = _factor(600.0, 600.0) * 1.0 / 2.0
        assert contributions == pytest.approx(facts[(1, 0, L.ImpactPoints)] + offset)
        assert facts[(1, 0, L.ContribEliminations)] == pytest.approx(_factor(600.0, 600.0) * 2.0 / 2.0)

    def test_rounds_carry_rank_and_points_but_no_breakdown_or_badge(self):
        stints = _stints(
            {"player_id": 1, "hero": 1, "seconds": 600.0, "Eliminations": 20.0},
            {"player_id": 1, "hero": 1, "seconds": 300.0, "Eliminations": 10.0, "segment": 1},
        )
        round_stats = {stat for _, segment, stat in _facts(stints, quintiles={1: 2}) if segment == 1}
        assert round_stats == {L.ImpactPoints, L.ImpactRank, L.OverperformanceScore}


class TestDominantRoles:
    def test_picks_role_with_most_playtime(self):
        stints = _stints(
            {"player_id": 1, "hero": 3, "seconds": 400.0},
            {"player_id": 1, "hero": 1, "seconds": 100.0},
            {"player_id": 2, "hero": 2, "seconds": 300.0},
            {"player_id": 3, "hero": 9, "seconds": 300.0},
        )
        assert impact.dominant_roles(stints) == {1: "tank", 2: "support"}
