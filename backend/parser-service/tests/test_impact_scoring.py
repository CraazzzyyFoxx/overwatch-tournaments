from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core import enums  # noqa: E402
from shared.core.impact import IMPACT_WEIGHTS  # noqa: E402
from src import models  # noqa: E402
from src.services.match_logs import impact  # noqa: E402

TANK = enums.HeroClass.tank
DAMAGE = enums.HeroClass.damage
SUPPORT = enums.HeroClass.support


def _kill(
    match_id=1, time=0.0, rnd=1, fight=1, killer=10, victim=20, killer_hero=1, victim_hero=2, ability=None, env=False
):
    return models.MatchKillFeed(
        match_id=match_id,
        time=time,
        round=rnd,
        fight=fight,
        killer_id=killer,
        killer_hero_id=killer_hero,
        killer_team_id=1,
        victim_id=victim,
        victim_hero_id=victim_hero,
        victim_team_id=2,
        ability=ability,
        damage=100.0,
        is_critical_hit=False,
        is_environmental=env,
    )


HERO_TYPES = {1: DAMAGE, 2: SUPPORT, 3: TANK}


class TestAssignFights:
    def test_new_fight_on_gap_and_round_change(self):
        feed = [
            _kill(time=1.0, rnd=1),
            _kill(time=5.0, rnd=1),  # same fight: 4s gap, same round
            _kill(time=25.0, rnd=1),  # new fight: 20s gap (>15) same round
            _kill(time=30.0, rnd=2),  # new fight: round change (even though 5s gap)
            _kill(time=31.0, rnd=2),  # same fight
        ]
        impact.assign_fights(feed)
        assert [k.fight for k in feed] == [1, 1, 2, 3, 3]

    def test_round_change_within_gap_still_splits(self):
        # <15s apart but different rounds → still a hard fight boundary.
        feed = [_kill(time=100.0, rnd=1), _kill(time=105.0, rnd=2)]
        impact.assign_fights(feed)
        assert [k.fight for k in feed] == [1, 2]

    def test_orders_by_time_before_assigning(self):
        later = _kill(time=30.0, rnd=1)
        earlier = _kill(time=1.0, rnd=1)
        impact.assign_fights([later, earlier])  # unsorted input
        assert earlier.fight == 1 and later.fight == 2  # 29s gap → two fights

    def test_empty_feed_is_noop(self):
        impact.assign_fights([])  # must not raise


class TestBuildEventCounts:
    def test_first_kill_of_each_fight_is_first_pick_and_first_death(self):
        feed = [
            _kill(time=1.0, fight=1, killer=10, victim=20),
            _kill(time=3.0, fight=1, killer=20, victim=10),  # not first
            _kill(time=40.0, fight=2, killer=20, victim=10),
        ]
        df = impact.build_event_counts(feed, HERO_TYPES)
        row10 = df[df.user_id == 10].iloc[0]
        row20 = df[df.user_id == 20].iloc[0]
        assert row10.FirstPicks == 1 and row10.FirstDeaths == 1
        assert row20.FirstPicks == 1 and row20.FirstDeaths == 1

    def test_self_kill_gives_first_death_but_not_first_pick(self):
        feed = [_kill(time=1.0, fight=1, killer=10, victim=10)]
        df = impact.build_event_counts(feed, HERO_TYPES)
        row = df[df.user_id == 10].iloc[0]
        assert row.FirstPicks == 0 and row.FirstDeaths == 1

    def test_ultimate_and_support_kills(self):
        feed = [
            _kill(time=1.0, killer=10, victim=20, victim_hero=2, ability=enums.AbilityEvent.Ultimate),
            _kill(time=2.0, killer=10, victim=20, victim_hero=3),  # tank victim
        ]
        df = impact.build_event_counts(feed, HERO_TYPES)
        row = df[df.user_id == 10].iloc[0]
        assert row.UltimateKills == 1
        assert row.SupportKills == 1  # only the hero-2 (support) victim

    def test_empty_feed_returns_empty_frame(self):
        df = impact.build_event_counts([], HERO_TYPES)
        assert df.empty


class TestBaselineSet:
    def _bs(self, mean=10.0, std=2.0):
        return impact.BaselineSet(
            formula_version="impact_v1",
            bucket_bounds=(500.0, 1000.0),
            values={("damage", -1, "Eliminations"): (mean, std)},
        )

    def test_z_and_winsorize(self):
        bs = self._bs()
        assert bs.z("damage", -1, "Eliminations", 12.0) == pytest.approx(1.0)
        assert bs.z("damage", -1, "Eliminations", 1000.0) == pytest.approx(3.0)  # clipped

    def test_missing_baseline_or_zero_std_is_zero(self):
        bs = self._bs(std=0.0)
        assert bs.z("damage", -1, "Eliminations", 12.0) == 0.0
        assert bs.z("tank", -1, "Eliminations", 12.0) == 0.0

    def test_bucket_for(self):
        bs = self._bs()
        assert bs.bucket_for(100) == 0
        assert bs.bucket_for(700) == 1
        assert bs.bucket_for(5000) == 2


class TestAddImpactScores:
    def _frame(self, elims=20.0, seconds=600.0, first_picks=3.0):
        cols = {
            "player_id": [1],
            "round": [0],
            enums.LogStatsName.Eliminations: [elims],
            enums.LogStatsName.HeroTimePlayed: [seconds],
            enums.LogStatsName.FirstPicks: [first_picks],
        }
        return pd.DataFrame(cols)

    def _players(self, role=DAMAGE, rank=800):
        return {1: impact.PlayerRef(player_id=1, user_id=10, team_id=1, role=role, rank=rank)}

    def _baselines(self):
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

    def test_composite_uses_weights_and_events(self):
        out = impact.add_impact_scores(
            self._frame(),
            players=self._players(),
            baselines=self._baselines(),
            has_killfeed=True,
        )
        # elims rate 20/10min -> z=2; first_picks rate 3 -> z=2; time_share=1
        expected = IMPACT_WEIGHTS["Eliminations"] * 2.0 + IMPACT_WEIGHTS["FirstPicks"] * 2.0
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == pytest.approx(expected)

    def test_no_killfeed_zeroes_event_z_only(self):
        out = impact.add_impact_scores(
            self._frame(),
            players=self._players(),
            baselines=self._baselines(),
            has_killfeed=False,
        )
        expected = IMPACT_WEIGHTS["Eliminations"] * 2.0
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == pytest.approx(expected)

    def test_short_playtime_scores_zero(self):
        out = impact.add_impact_scores(
            self._frame(seconds=30.0),
            players=self._players(),
            baselines=self._baselines(),
            has_killfeed=True,
        )
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == 0.0
        assert out[enums.LogStatsName.OverperformanceScore].iloc[0] == 0.0

    def test_overperformance_uses_rank_bucket_baseline(self):
        out = impact.add_impact_scores(
            self._frame(),
            players=self._players(rank=700),
            baselines=self._baselines(),
            has_killfeed=True,
        )
        # bucket 1: elims z=(20-12)/5=1.6, fp z=(3-1.5)/1=1.5
        expected = IMPACT_WEIGHTS["Eliminations"] * 1.6 + IMPACT_WEIGHTS["FirstPicks"] * 1.5
        assert out[enums.LogStatsName.OverperformanceScore].iloc[0] == pytest.approx(expected)

    def test_unknown_role_scores_zero(self):
        out = impact.add_impact_scores(
            self._frame(),
            players=self._players(role=None),
            baselines=self._baselines(),
            has_killfeed=True,
        )
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == 0.0

    def test_nan_stat_cell_contributes_zero(self):
        # Eliminations baseline mean is 0 so a correctly-zeroed NaN cell
        # contributes exactly 0 to ImpactPoints (rate=0 -> z=(0-0)/std=0).
        # On the buggy code the NaN cell survives into `rate`/`z` and the
        # winsorize clamp silently resolves it to +WINSOR_LIMIT instead.
        baselines = impact.BaselineSet(
            formula_version="impact_v1",
            bucket_bounds=(500.0, 1000.0),
            values={
                ("damage", -1, "Eliminations"): (0.0, 5.0),
                ("damage", -1, "FirstPicks"): (1.0, 1.0),
            },
        )
        out = impact.add_impact_scores(
            self._frame(elims=float("nan")),
            players=self._players(),
            baselines=baselines,
            has_killfeed=True,
        )
        # first_picks rate 3 -> z=2; NaN Eliminations term must drop to 0,
        # NOT IMPACT_WEIGHTS["Eliminations"] * WINSOR_LIMIT.
        expected = IMPACT_WEIGHTS["FirstPicks"] * 2.0
        assert out[enums.LogStatsName.ImpactPoints].iloc[0] == pytest.approx(expected)


class TestDominantRoles:
    def test_picks_role_with_most_playtime(self):
        df = pd.DataFrame(
            {
                "player_id": [1, 1, 2],
                "hero_id": [1, 3, 2],
                "seconds": [100.0, 400.0, 300.0],
            }
        )
        roles = impact.dominant_roles(df, HERO_TYPES)
        assert roles == {1: TANK, 2: SUPPORT}
