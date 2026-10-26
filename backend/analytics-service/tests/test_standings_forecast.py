"""Stage B must forecast the field, not restate the bracket.

Two defects, one fix. ``run_standings_for_tournament`` used to simulate the
tournament's own encounters, so (a) an unplayed bracket produced no matchups,
no ``analytics.standings_distribution`` rows and therefore no predicted places
at all, and (b) a played bracket leaked its result into the forecast: pairings
in an elimination round are decided by who won the previous one, and ranking by
win count over that schedule rewards teams simply for having advanced. Stage B
now always simulates a virtual double round robin over the registered teams.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


standings_features = importlib.import_module("src.services.ml.features.standings_features")
from tests.ow_analytics import exports as ow_exports  # noqa: E402
from tests.ow_analytics import module as ow_module  # noqa: E402

standings_v2 = ow_module("models.standings_v2")
runner = importlib.import_module("src.services.ml.inference.runner")


def _rank_stats(rows: list[tuple[int, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["team_id", "avg_rank", "std_rank"])


def _mu(rows: list[tuple[int, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["team_id", "avg_mu"])
    for col in ("max_mu", "min_mu", "std_mu", "tank_mu", "damage_mu", "support_mu"):
        frame[col] = 0.0
    return frame


def _synergy(rows: list[tuple[int, float, float]] | None = None) -> pd.DataFrame:
    return pd.DataFrame(rows or [], columns=["team_id", "synergy_pairs", "synergy_winrate"])


class ScheduleLeakageTests(TestCase):
    """The reason Stage B may not simulate the realised bracket.

    Eight teams of *identical* strength — every win-probability is exactly 0.5,
    so a sound simulator must rank them all alike. Fed the played
    single-elimination bracket it does not: the finalists appear in three
    encounters and can bank three wins while a round-one loser appears once, so
    the ranking reproduces how far each team actually got.
    """

    QUARTER_FINAL_LOSERS = (2, 4, 6, 8)

    def _simulate(self, matchups: pd.DataFrame, teams: list[int]) -> dict[int, float]:
        distribution = standings_v2.simulate_standings(
            matchups,
            teams,
            n_iter=4000,
            rng=np.random.default_rng(0),
        )
        return {int(r.team_id): float(r.prob_top1) for r in distribution.itertuples(index=False)}

    def test_realised_bracket_ranks_equal_teams_by_how_far_they_advanced(self) -> None:
        teams = [1, 2, 3, 4, 5, 6, 7, 8]
        realised = pd.DataFrame(
            {
                # QF winners 1,3,5,7 → SF winners 1,5 → final won by 1.
                "home_team_id": [1, 3, 5, 7, 1, 5, 1],
                "away_team_id": [2, 4, 6, 8, 3, 7, 5],
                "p_home_wins": [0.5] * 7,
            }
        )

        top1 = self._simulate(realised, teams)
        finalists = min(top1[1], top1[5])
        eliminated = max(top1[team] for team in self.QUARTER_FINAL_LOSERS)

        # Same strength, wildly different forecast — purely from the schedule.
        self.assertGreater(finalists, eliminated * 5)

    def test_double_round_robin_ranks_equal_teams_alike(self) -> None:
        teams = [1, 2, 3, 4, 5, 6, 7, 8]
        pairs = [(home, away) for home in teams for away in teams if home != away]
        round_robin = pd.DataFrame(
            {
                "home_team_id": [home for home, _ in pairs],
                "away_team_id": [away for _, away in pairs],
                "p_home_wins": [0.5] * len(pairs),
            }
        )

        top1 = self._simulate(round_robin, teams)

        # Every team within a point of the uniform 1/8, no structural winners.
        for team, probability in top1.items():
            self.assertAlmostEqual(0.125, probability, delta=0.01, msg=f"team {team}")


class ForecastFrameTests(IsolatedAsyncioTestCase):
    async def _build(self, ranks, mus, synergy=None):
        with (
            patch.object(ow_exports, "team_rank_stats", AsyncMock(return_value=_rank_stats(ranks))),
            patch.object(
                standings_features,
                "snapshot_pre_tournament_team_mu",
                AsyncMock(return_value=_mu(mus)),
            ),
            patch.object(
                ow_exports,
                "team_synergy_features",
                AsyncMock(return_value=_synergy(synergy)),
            ),
        ):
            return await standings_features.build_standings_forecast_frame(SimpleNamespace(), 7, discipline="overwatch")

    async def test_every_ordered_pair_is_emitted_once(self) -> None:
        frame = await self._build(
            [(10, 3000.0, 100.0), (20, 2500.0, 50.0), (30, 2000.0, 0.0)],
            [(10, 3100.0), (20, 2400.0), (30, 1900.0)],
        )

        pairs = {(int(r.home_team_id), int(r.away_team_id)) for r in frame.itertuples(index=False)}
        self.assertEqual(6, len(frame))
        self.assertEqual(
            {(10, 20), (20, 10), (10, 30), (30, 10), (20, 30), (30, 20)},
            pairs,
        )
        # Both orientations of a pair exist, so any learned home-side bias
        # cancels across the simulated round robin.
        self.assertTrue(all((away, home) in pairs for home, away in pairs))

    async def test_feature_contract_is_satisfied(self) -> None:
        frame = await self._build(
            [(10, 3000.0, 100.0), (20, 2500.0, 50.0)],
            [(10, 3100.0), (20, 2400.0)],
        )

        for column in standings_v2.STANDINGS_FEATURE_ORDER:
            self.assertIn(column, frame.columns, column)

        row = frame[(frame["home_team_id"] == 10) & (frame["away_team_id"] == 20)].iloc[0]
        self.assertEqual(500.0, row["rank_gap"])
        self.assertEqual(700.0, row["mu_gap"])
        # The mu spread features ride the same snapshot; the helper pins them
        # to zero, so their gaps are exactly zero — present and numeric.
        self.assertEqual(0.0, row["max_mu_gap"])
        self.assertEqual(0.0, row["home_std_mu"])
        self.assertEqual(7, row["tournament_id"])

    async def test_synergy_reaches_both_sides_of_a_pairing(self) -> None:
        frame = await self._build(
            [(10, 3000.0, 100.0), (20, 2500.0, 50.0)],
            [(10, 3100.0), (20, 2400.0)],
            synergy=[(10, 0.4, 0.75), (20, 0.1, 0.25)],
        )

        row = frame[(frame["home_team_id"] == 10) & (frame["away_team_id"] == 20)].iloc[0]
        self.assertEqual(0.4, row["home_synergy_pairs"])
        self.assertEqual(0.25, row["away_synergy_winrate"])
        self.assertAlmostEqual(0.5, row["synergy_winrate_gap"])

    async def test_no_synergy_history_stays_missing_not_average(self) -> None:
        frame = await self._build(
            [(10, 3000.0, 100.0), (20, 2500.0, 50.0)],
            [(10, 3100.0), (20, 2400.0)],
            synergy=None,
        )
        self.assertTrue(frame["home_synergy_winrate"].isna().all())
        self.assertTrue(frame["synergy_winrate_gap"].isna().all())

    async def test_single_team_field_yields_nothing_to_simulate(self) -> None:
        frame = await self._build([(10, 3000.0, 100.0)], [(10, 3100.0)])
        self.assertTrue(frame.empty)

    async def test_team_without_mu_history_still_gets_a_row(self) -> None:
        # A brand-new roster has no OpenSkill snapshot; the pairing must still
        # be simulated (rank features carry it) instead of vanishing.
        frame = await self._build(
            [(10, 3000.0, 100.0), (20, 2500.0, 50.0)],
            [(10, 3100.0)],
        )

        self.assertEqual(2, len(frame))
        self.assertTrue(frame[frame["away_team_id"] == 20]["away_avg_mu"].isna().all())


class _StubModel:
    """Win-probability stand-in: home wins iff it has the higher mean rank."""

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return np.where(df["rank_gap"].to_numpy(dtype=float) > 0, 0.9, 0.1)


class StandingsRunnerTests(IsolatedAsyncioTestCase):
    def _patches(self, forecast: pd.DataFrame):
        session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        return session, (
            patch.object(runner, "_algorithm_id", AsyncMock(return_value=1)),
            patch.object(
                runner.registry_service,
                "load_active_artifact",
                AsyncMock(return_value=SimpleNamespace(storage_uri="s")),
            ),
            patch.object(runner, "load_artifact_or_none", lambda _uri: _StubModel()),
            patch.object(runner, "build_standings_forecast_frame", AsyncMock(return_value=forecast)),
            patch.object(runner, "tournament_module", AsyncMock(return_value=("overwatch", ow_exports))),
        )

    @staticmethod
    def _forecast() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "home_team_id": [10, 20],
                "away_team_id": [20, 10],
                "rank_gap": [500.0, -500.0],
            }
        )

    async def test_forecast_frame_drives_the_simulation(self) -> None:
        session, patches = self._patches(self._forecast())

        with patches[0], patches[1], patches[2], patches[3] as forecast_call, patches[4]:
            written = await runner.run_standings_for_tournament(session, 7, workspace_id=3, n_iter=50)

        forecast_call.assert_awaited_once()
        self.assertEqual(7, forecast_call.await_args.args[1])
        self.assertEqual(3, forecast_call.await_args.kwargs["workspace_id"])
        self.assertEqual("overwatch", forecast_call.await_args.kwargs["discipline"])
        self.assertEqual(2, written)
        # The read transaction ends before the simulation; the rows commit after it.
        self.assertEqual(2, session.commit.await_count)

    def test_encounter_frame_is_out_of_reach_of_stage_b(self) -> None:
        # The leak guard, pinned at the bluntest level there is: the inference
        # runner must not even hold a reference to the encounter-driven builder,
        # so no future edit can quietly route the realised bracket back into the
        # simulator. Training and Match Quality still use it — from their own
        # modules.
        self.assertFalse(
            hasattr(runner, "build_standings_training_frame"),
            "Stage B must simulate the forecast frame, never the played encounters",
        )

    async def test_unrateable_field_writes_nothing(self) -> None:
        session, patches = self._patches(pd.DataFrame())

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            written = await runner.run_standings_for_tournament(session, 7, workspace_id=3, n_iter=50)

        self.assertEqual(0, written)
        session.commit.assert_not_awaited()
