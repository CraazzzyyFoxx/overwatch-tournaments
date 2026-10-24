from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


from tests.ow_analytics import exports as ow_exports  # noqa: E402
from tests.ow_analytics import module as ow_module  # noqa: E402

performance_v2 = ow_module("models.performance_v2")
shift_features = ow_module("features.shift_features")
shift_v2 = ow_module("models.shift_v2")
MVP_MIN_MATCHES = ow_module("features.mvp_dominance").MVP_MIN_MATCHES

from shared.division_grid import DEFAULT_GRID  # noqa: E402
from src.services.ml.inference import runner  # noqa: E402
from tests.factories import identity_assign as _identity_assign

# The shift ramps are keyed on the canonical ladder (DEFAULT_GRID), so tests that
# mean "at the bottom" / "mid-ladder" name those positions instead of hardcoding
# a number: adding a division (Emerald) lengthens the ladder below the top and
# moves both.
CANONICAL_BOTTOM_DIV = DEFAULT_GRID.max_division
CANONICAL_MID_DIV = (DEFAULT_GRID.min_division + DEFAULT_GRID.max_division) // 2


class ShiftRankHistoryTests(IsolatedAsyncioTestCase):
    async def test_explicit_history_horizon_keeps_sparse_future_tournament_labels(self) -> None:
        # rank doubles as the canonical division under the identity stub; the two
        # tournaments use different source grid versions but land on one scale.
        rows = [
            {
                "player_id": 1,
                "user_id": 10,
                "role": "tank",
                "tournament_id": 10,
                "started_at": datetime(2026, 1, 10, tzinfo=UTC),
                "rank": 7,
                "is_newcomer": False,
                "version_id": 2,
            },
            {
                "player_id": 2,
                "user_id": 10,
                "role": "tank",
                "tournament_id": 20,
                "started_at": datetime(2026, 1, 20, tzinfo=UTC),
                "rank": 6,
                "is_newcomer": False,
                "version_id": 11,
            },
        ]
        result = SimpleNamespace(
            mappings=lambda: SimpleNamespace(all=lambda: rows),
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        with (
            patch.object(shift_features, "load_division_grids", AsyncMock(return_value={})),
            patch.object(shift_features, "assign_canonical_division", _identity_assign),
        ):
            history = await shift_features.load_player_rank_history(
                session,
                [10],
                history_through_tournament_id=20,
            )

        first_row = history.loc[history["tournament_id"] == 10].iloc[0]
        self.assertEqual(7, first_row["div"])
        self.assertEqual(6, first_row["next_tournament_div"])

        # The horizon tournament reaches the SQL bound (an IN-list param of the horizon subquery).
        query = session.execute.await_args.args[0]
        values = query.compile().params.values()
        params = [v for value in values for v in (value if isinstance(value, list) else [value])]
        self.assertIn(20, params)

    async def test_unranked_tournament_has_no_division_and_does_not_break_the_chronology(self) -> None:
        rows = [
            {
                "player_id": pid,
                "user_id": 10,
                "role": "tank",
                "tournament_id": tid,
                "started_at": datetime(2026, 1, tid, tzinfo=UTC),
                "rank": rank,
                "is_newcomer": False,
                "version_id": None,
            }
            for pid, tid, rank in ((1, 10, 2500), (2, 20, None), (3, 30, 2510))
        ]
        result = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
        session = SimpleNamespace(execute=AsyncMock(return_value=result))

        with patch.object(shift_features, "load_division_grids", AsyncMock(return_value={})):
            history = await shift_features.load_player_rank_history(session, [10, 20, 30])

        div = DEFAULT_GRID.resolve_division(2500).number
        self.assertEqual(div, DEFAULT_GRID.resolve_division(2510).number)
        first, unranked, last = (history.loc[history["tournament_id"] == tid].iloc[0] for tid in (10, 20, 30))
        self.assertEqual(div, first["next_tournament_div"])
        self.assertEqual(div, last["prior_div"])
        self.assertEqual(2, last["tournaments_at_current_div"])
        for column in ("div", "prior_div", "next_tournament_div", "tournaments_at_current_div"):
            self.assertTrue(pd.isna(unranked[column]), column)
        # Participation is not rank-based: the unranked tournament still counts.
        self.assertEqual([1, 2, 3], history["tournaments_played"].tolist())


class ShiftBlendTests(TestCase):
    def test_blend_columns_cover_team_os_and_impact(self) -> None:
        self.assertIn("linear_stable_shift", shift_v2.SHIFT_BLEND_COLUMNS)
        self.assertIn("os_shift", shift_v2.SHIFT_BLEND_COLUMNS)
        self.assertIn("performance_v2_local_zscore", shift_v2.SHIFT_BLEND_COLUMNS)

    def test_backbone_is_weighted_team_plus_os(self) -> None:
        model = shift_v2.ShiftModelV2(w_team=0.7, w_os=0.3, indiv_scale_top=0.5, indiv_scale_bottom=0.5)
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [1.0],
                "os_shift": [-2.0],
                "performance_v2_local_zscore": [0.0],
                "tournaments_played": [3],
                "is_newcomer": [False],
            }
        )

        # backbone = 0.7*1.0 + 0.3*(-2.0) = 0.1; indiv = 0.5*0 = 0.
        self.assertAlmostEqual(0.1, float(model.predict(frame).iloc[0]), places=6)

    def test_individual_skill_is_additive_and_widened(self) -> None:
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=1.5,
            indiv_clamp_bottom=1.5,
        )
        base = {"linear_stable_shift": [0.0], "os_shift": [0.0], "tournaments_played": [3], "is_newcomer": [False]}

        # A clear individual outlier on a flat team still moves: 0.5*3 = 1.5
        # (vs the old ±0.5/weight-0 design where it was ~0).
        s3 = float(model.predict(pd.DataFrame({**base, "performance_v2_local_zscore": [3.0]})).iloc[0])
        s1 = float(model.predict(pd.DataFrame({**base, "performance_v2_local_zscore": [1.0]})).iloc[0])
        self.assertAlmostEqual(1.5, s3, places=6)
        self.assertAlmostEqual(0.5, s1, places=6)
        # Clamped: a huge z saturates at the clamp, not beyond.
        s_big = float(model.predict(pd.DataFrame({**base, "performance_v2_local_zscore": [9.0]})).iloc[0])
        self.assertAlmostEqual(1.5, s_big, places=6)

    def test_individual_lifts_outlier_on_top_of_team(self) -> None:
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=1.5,
            indiv_clamp_bottom=1.5,
        )
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [1.0],
                "os_shift": [1.0],
                "performance_v2_local_zscore": [2.0],
                "tournaments_played": [3],
                "is_newcomer": [False],
            }
        )
        # backbone = 1.0; indiv = 0.5*2 = 1.0 → 2.0 (individual adds on top).
        self.assertAlmostEqual(2.0, float(model.predict(frame).iloc[0]), places=6)

    def test_newcomer_uses_clipped_team_backbone_only(self) -> None:
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=1.5,
            indiv_clamp_bottom=1.5,
        )
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [2.0],
                "os_shift": [2.0],
                "performance_v2_local_zscore": [3.0],
                "tournaments_played": [1],  # newcomer
                "is_newcomer": [True],
            }
        )
        # backbone = 2.0 → clipped to newcomer range 1.5; individual term ignored.
        self.assertAlmostEqual(1.5, float(model.predict(frame).iloc[0]), places=6)

    def test_individual_modifier_ramps_with_rank(self) -> None:
        # Same outlier, flat team: the individual lift is small near the ceiling
        # (canonical division 1) and large at the bottom of the canonical ladder.
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.2,
            indiv_scale_bottom=0.8,
            indiv_clamp_top=0.75,
            indiv_clamp_bottom=2.0,
        )
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [0.0],
            "tournaments_played": [3],
            "is_newcomer": [False],
            "performance_v2_local_zscore": [2.0],
        }
        top = float(model.predict(pd.DataFrame({**base, "current_div": [1]})).iloc[0])
        bottom = float(model.predict(pd.DataFrame({**base, "current_div": [CANONICAL_BOTTOM_DIV]})).iloc[0])
        # top: 0.2*2 = 0.40 ; bottom: 0.8*2 = 1.60.
        self.assertAlmostEqual(0.40, top, places=6)
        self.assertAlmostEqual(1.60, bottom, places=6)
        self.assertLess(top, bottom)

    def test_individual_clamp_ramps_with_rank(self) -> None:
        # A blatant outlier saturates at the rank-dependent clamp, not a flat one.
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.2,
            indiv_scale_bottom=0.8,
            indiv_clamp_top=0.75,
            indiv_clamp_bottom=2.0,
        )
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [0.0],
            "tournaments_played": [3],
            "is_newcomer": [False],
            "performance_v2_local_zscore": [9.0],
        }
        top = float(model.predict(pd.DataFrame({**base, "current_div": [1]})).iloc[0])
        bottom = float(model.predict(pd.DataFrame({**base, "current_div": [CANONICAL_BOTTOM_DIV]})).iloc[0])
        self.assertAlmostEqual(0.75, top, places=6)  # capped tight near the ceiling
        self.assertAlmostEqual(2.0, bottom, places=6)  # full range at the bottom

    def test_missing_division_falls_back_to_mid_ladder(self) -> None:
        # No current_div → neutral mid-ladder ramp (no over-/under-promotion).
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.2,
            indiv_scale_bottom=0.8,
            indiv_clamp_top=0.75,
            indiv_clamp_bottom=2.0,
        )
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [0.0],
                "os_shift": [0.0],
                "tournaments_played": [3],
                "is_newcomer": [False],
                "performance_v2_local_zscore": [2.0],
            }
        )
        # mid t=0.5 → scale 0.5 → 0.5*2 = 1.0 (within mid clamp 1.375).
        self.assertAlmostEqual(1.0, float(model.predict(frame).iloc[0]), places=6)

    def test_output_clamp_squeezes_top_by_grid_size(self) -> None:
        # A top-rank player (canonical division 1) whose backbone alone wants ±3:
        # the output clamp squeezes it, and the cap scales with grid size.
        model = shift_v2.ShiftModelV2(w_team=0.7, w_os=0.3, clamp_top_grid_ref=20.0)
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [10.0],  # backbone = 3.0
            "performance_v2_local_zscore": [0.0],
            "tournaments_played": [3],
            "is_newcomer": [False],
            "current_div": [1],
        }
        s20 = float(model.predict(pd.DataFrame({**base, "grid_n_div": [20]})).iloc[0])
        s40 = float(model.predict(pd.DataFrame({**base, "grid_n_div": [40]})).iloc[0])
        self.assertAlmostEqual(1.0, s20, places=6)  # 20-tier grid → +-1 at the top
        self.assertAlmostEqual(2.0, s40, places=6)  # 40-tier grid → +-2 at the top

    def test_output_clamp_keeps_full_range_at_bottom(self) -> None:
        # Lowest rank keeps the full +-3 regardless of grid size.
        model = shift_v2.ShiftModelV2(w_team=0.7, w_os=0.3, clamp_top_grid_ref=20.0)
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [0.0],
                "os_shift": [20.0],
                "performance_v2_local_zscore": [0.0],
                "tournaments_played": [3],
                "is_newcomer": [False],
                "current_div": [CANONICAL_BOTTOM_DIV],
                "grid_n_div": [20],
            }
        )
        self.assertAlmostEqual(3.0, float(model.predict(frame).iloc[0]), places=6)

    def test_output_clamp_regression_tref_case(self) -> None:
        # Real prod case (tournament 73, Tref): GM-zone player (canonical division
        # 9 = Grandmaster 4) in a 20-tier grid whose +3 came from a huge os_shift.
        # With the rank/grid output clamp the OpenSkill+ML shift is held near +1.4
        # instead of saturating at +3. The expected value tracks the canonical
        # ladder length: Emerald added five divisions BELOW this player, so the
        # same real rank now sits proportionally higher (t = 8/44, was 8/39) and
        # the clamp tightens from 1.41 to 1.36.
        model = shift_v2.ShiftModelV2()  # config defaults
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [1.216],
                "os_shift": [6.0],
                "performance_v2_local_zscore": [2.318],
                "tournaments_played": [37],
                "is_newcomer": [False],
                "current_div": [9],
                "grid_n_div": [20],
            }
        )
        self.assertAlmostEqual(1.36, float(model.predict(frame).iloc[0]), places=2)

    def test_raw_mvp_dominance_lifts_bounded_only_by_output_clamp(self) -> None:
        # A consistent scoreboard-topper: the dominance lift bypasses the softer
        # local scale/clamp and is bounded only by the rank/grid output clamp.
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=2.0,
            indiv_clamp_bottom=2.0,
            dominance_gain=4.0,
            dominance_cap=2.0,
        )
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [0.0],
            "performance_v2_local_zscore": [0.3],
            "current_div": [20],
            "grid_n_div": [40],
            "tournaments_played": [5],
            "is_newcomer": [False],
            "mvp_matches": [MVP_MIN_MATCHES],
        }
        # dominance 0.81 → dominance_z=(0.81-0.5)*4=1.24, under out_clamp (~2.49),
        # NOT scaled by the local 0.5 → individual term 1.24 (was 0.62 when scaled).
        s_dom = float(model.predict(pd.DataFrame({**base, "mvp_dominance": [0.81]})).iloc[0])
        # neutral dominance 0.5 → dominance_z 0 → falls back to local term 0.5*0.3.
        s_neu = float(model.predict(pd.DataFrame({**base, "mvp_dominance": [0.5]})).iloc[0])
        self.assertAlmostEqual(1.24, s_dom, places=2)
        self.assertAlmostEqual(0.15, s_neu, places=2)
        self.assertGreater(s_dom, s_neu)

    def test_dominance_lift_is_bounded_by_rank_output_clamp(self) -> None:
        # The same blatant dominator is held tighter near the ceiling (small output
        # clamp) than mid-ladder — dominance can't yank a high rank.
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            dominance_gain=6.0,
            dominance_cap=3.0,
            clamp_top_grid_ref=20.0,
        )
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [0.0],
            "performance_v2_local_zscore": [0.0],
            "grid_n_div": [20],
            "tournaments_played": [5],
            "is_newcomer": [False],
            "mvp_dominance": [1.0],
            "mvp_matches": [MVP_MIN_MATCHES],
        }
        top = float(model.predict(pd.DataFrame({**base, "current_div": [1]})).iloc[0])
        mid = float(model.predict(pd.DataFrame({**base, "current_div": [CANONICAL_MID_DIV]})).iloc[0])
        # div 1 (grid 20): output clamp = 1.0 → lift capped at 1.0.
        self.assertAlmostEqual(1.0, top, places=2)
        # mid-ladder (t = 0.5): output clamp = 1.0+(3-1)*0.5 = 2.0 → dominance_z 3.0
        # capped to it.
        self.assertAlmostEqual(2.0, mid, places=2)
        self.assertGreater(mid, top)

    def test_placement_gates_whole_positive_shift(self) -> None:
        # The WHOLE positive shift is gated by team placement — including a
        # backbone driven by a (spurious) large os_shift, not just the individual
        # lift. Mirrors the prod case: a 2-8 last-placed player with os_shift 11.
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            dominance_gain=6.0,
            dominance_cap=3.0,
            placement_floor=0.0,
            clamp_top_grid_ref=20.0,
        )
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [11.0],
            "performance_v2_local_zscore": [-0.8],
            "mvp_dominance": [0.41],
            "current_div": [26],
            "grid_n_div": [20],
            "tournaments_played": [5],
            "is_newcomer": [False],
            "team_count": [32],
        }
        s_win = float(model.predict(pd.DataFrame({**base, "overall_position": [0]})).iloc[0])
        s_last = float(model.predict(pd.DataFrame({**base, "overall_position": [31]})).iloc[0])
        # winner: backbone-driven shift survives; near-last: gated to ~0.
        self.assertGreater(s_win, 2.0)
        self.assertLess(s_last, 0.2)
        self.assertGreaterEqual(s_last, 0.0)

    def test_placement_gate_passes_through_demotions_and_missing_standings(self) -> None:
        model = shift_v2.ShiftModelV2(w_team=0.7, w_os=0.3, placement_floor=0.0)
        # Negative shift on a last-placed team is NOT attenuated (demotion stands).
        neg = pd.DataFrame(
            {
                "linear_stable_shift": [-2.0],
                "os_shift": [-2.0],
                "performance_v2_local_zscore": [-0.5],
                "current_div": [26],
                "grid_n_div": [20],
                "tournaments_played": [5],
                "is_newcomer": [False],
                "overall_position": [31],
                "team_count": [32],
            }
        )
        self.assertLess(float(model.predict(neg).iloc[0]), -0.5)
        # Missing standings → no gate (positive shift survives).
        nostd = pd.DataFrame(
            {
                "linear_stable_shift": [2.0],
                "os_shift": [2.0],
                "performance_v2_local_zscore": [0.0],
                "current_div": [26],
                "grid_n_div": [20],
                "tournaments_played": [5],
                "is_newcomer": [False],
            }
        )
        self.assertGreater(float(model.predict(nostd).iloc[0]), 1.0)

    def test_low_dominance_does_not_push_down(self) -> None:
        # A low scoreboard position must not drag the individual term negative.
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=2.0,
            indiv_clamp_bottom=2.0,
        )
        frame = pd.DataFrame(
            {
                "linear_stable_shift": [0.0],
                "os_shift": [0.0],
                "performance_v2_local_zscore": [0.0],
                "current_div": [20],
                "grid_n_div": [40],
                "tournaments_played": [5],
                "is_newcomer": [False],
                "mvp_dominance": [0.1],
                "mvp_matches": [MVP_MIN_MATCHES],
            }
        )
        # dominance_z floored at 0; local_z 0 → individual term 0.
        self.assertAlmostEqual(0.0, float(model.predict(frame).iloc[0]), places=6)

    def _mvp_model(self) -> shift_v2.ShiftModelV2:
        return shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=1.5,
            indiv_clamp_bottom=1.5,
            dominance_gain=4.0,
            dominance_cap=2.0,
        )

    def test_negative_local_z_lowers_the_shift_unless_an_mvp_lift_wins(self) -> None:
        model = self._mvp_model()
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [0.0],
            "performance_v2_local_zscore": [-2.0],
            "tournaments_played": [3],
            "is_newcomer": [False],
        }
        # No MVP lift: the local term applies as is, 0.5 * -2 = -1.0.
        self.assertAlmostEqual(-1.0, float(model.predict(pd.DataFrame(base)).iloc[0]), places=6)
        # An MVP lift (upward only) replaces the smaller local term: (0.81 - 0.5) * 4 = 1.24.
        lifted = {**base, "mvp_dominance": [0.81], "mvp_matches": [MVP_MIN_MATCHES]}
        self.assertAlmostEqual(1.24, float(model.predict(pd.DataFrame(lifted)).iloc[0]), places=6)

    def test_mvp_lift_needs_the_minimum_logged_matches(self) -> None:
        model = self._mvp_model()
        base = {
            "linear_stable_shift": [0.0],
            "os_shift": [0.0],
            "performance_v2_local_zscore": [0.0],
            "tournaments_played": [3],
            "is_newcomer": [False],
            "mvp_dominance": [0.81],
        }
        few = pd.DataFrame({**base, "mvp_matches": [MVP_MIN_MATCHES - 1]})
        enough = pd.DataFrame({**base, "mvp_matches": [MVP_MIN_MATCHES]})
        self.assertAlmostEqual(0.0, float(model.predict(few).iloc[0]), places=6)
        self.assertAlmostEqual(1.24, float(model.predict(enough).iloc[0]), places=6)


class ShiftUncertaintyTests(TestCase):
    BASE = {
        "linear_stable_shift": [0.0],
        "linear_shift_sd": [0.4],
        "os_shift": [0.0],
        "os_shift_sd": [0.3],
        "tournaments_played": [3],
        "is_newcomer": [False],
    }
    # (w_team * sd_lin)^2 + (w_os * sd_os)^2
    BACKBONE_VAR = (0.7 * 0.4) ** 2 + (0.3 * 0.3) ** 2

    def _predict(self, **columns: list) -> pd.Series:
        model = shift_v2.ShiftModelV2(
            w_team=0.7,
            w_os=0.3,
            indiv_scale_top=0.5,
            indiv_scale_bottom=0.5,
            indiv_clamp_top=1.5,
            indiv_clamp_bottom=1.5,
            dominance_gain=4.0,
            dominance_cap=2.0,
        )
        return model.predict_with_uncertainty(pd.DataFrame({**self.BASE, **columns})).iloc[0]

    def test_sd_combines_the_backbone_and_the_active_individual_term(self) -> None:
        # No individual term applies: the backbone alone.
        self.assertAlmostEqual(np.sqrt(self.BACKBONE_VAR), self._predict()["shift_sd"])
        # The local term: its per-match scale (0.5) over sqrt(logged matches).
        local = self._predict(performance_v2_local_zscore=[-1.0], mvp_matches=[4])
        self.assertAlmostEqual(np.sqrt(self.BACKBONE_VAR + (0.5 / 2) ** 2), local["shift_sd"])
        # The MVP lift: gain x the sd of a uniform rank position (1/sqrt(12)), over sqrt(logged matches).
        mvp = self._predict(performance_v2_local_zscore=[0.3], mvp_dominance=[0.81], mvp_matches=[9])
        self.assertAlmostEqual(np.sqrt(self.BACKBONE_VAR + (4.0 / np.sqrt(12.0) / 3) ** 2), mvp["shift_sd"])

    def test_newcomer_sd_is_the_backbone_only(self) -> None:
        newcomer = self._predict(
            performance_v2_local_zscore=[-2.0], mvp_matches=[4], tournaments_played=[1], is_newcomer=[True]
        )
        self.assertAlmostEqual(np.sqrt(self.BACKBONE_VAR), newcomer["shift_sd"])

    def test_placement_gate_scales_the_sd_with_the_shift(self) -> None:
        ungated = self._predict(linear_stable_shift=[2.0])
        # Third of five teams: the positive shift and its sd are both halved.
        gated = self._predict(linear_stable_shift=[2.0], overall_position=[3], team_count=[5])
        self.assertAlmostEqual(0.5 * ungated["shift_v2"], gated["shift_v2"])
        self.assertAlmostEqual(0.5 * ungated["shift_sd"], gated["shift_sd"])

    def test_missing_linear_falls_back_to_the_openskill_sd_and_an_unknown_sd_stays_unknown(self) -> None:
        fallback = self._predict(linear_stable_shift=[np.nan])
        self.assertAlmostEqual(np.sqrt((0.7 * 0.3) ** 2 + (0.3 * 0.3) ** 2), fallback["shift_sd"])
        self.assertTrue(np.isnan(self._predict(linear_shift_sd=[np.nan])["shift_sd"]))


class ShiftRunnerTests(IsolatedAsyncioTestCase):
    async def test_the_runner_persists_the_shift_sd(self) -> None:
        frame = pd.DataFrame(
            {
                "tournament_id": [7, 7],
                "player_id": [1, 2],
                "linear_stable_shift": [1.0, 0.5],
                "linear_shift_sd": [0.4, np.nan],
                "os_shift": [0.5, 0.0],
                "os_shift_sd": [0.3, 0.2],
                "tournaments_played": [3, 3],
            }
        )
        session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        model = shift_v2.ShiftModelV2()
        with (
            patch.object(runner, "tournament_module", AsyncMock(return_value=("overwatch", ow_exports))),
            patch.object(runner, "_algorithm_id", AsyncMock(return_value=4)),
            patch.object(
                runner.registry_service,
                "load_active_artifact",
                AsyncMock(return_value=SimpleNamespace(storage_uri="s")),
            ),
            patch.object(runner, "load_artifact_or_none", lambda _uri: model),
            patch.object(runner, "build_shift_feature_frame", AsyncMock(return_value=frame)),
        ):
            written = await runner.run_shift_for_tournament(session, 7, workspace_id=3)

        self.assertEqual(2, written)
        rows = session.execute.await_args_list[-1].args[1]
        self.assertAlmostEqual(np.sqrt((0.7 * 0.4) ** 2 + (0.3 * 0.3) ** 2), rows[0]["shift_sd"])
        self.assertIsNone(rows[1]["shift_sd"])  # an unknown Linear sd leaves the shift sd unknown
        self.assertNotIn("confidence", rows[0])


class ShiftTrainTests(TestCase):
    def _frame(self, n: int, *, seed: int) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        team = rng.uniform(-1.5, 1.5, n)
        current_div = np.full(n, 10.0)
        return pd.DataFrame(
            {
                "tournament_id": [seed] * n,
                "current_div": current_div,
                "next_tournament_div": current_div - team,
                "linear_stable_shift": team,
                "os_shift": rng.normal(0.0, 0.2, n),
                "performance_v2_local_zscore": rng.normal(0.0, 1.0, n),
            }
        )

    def test_empty_frame_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, r"empty"):
            shift_v2.train_shift_v2(pd.DataFrame())

    def test_snapshots_config_weights(self) -> None:
        result = shift_v2.train_shift_v2(
            self._frame(60, seed=1),
            w_team=0.8,
            w_os=0.2,
            indiv_scale_top=0.1,
            indiv_scale_bottom=0.4,
            indiv_clamp_top=0.5,
            indiv_clamp_bottom=2.0,
            clamp_top_grid_ref=25.0,
        )
        self.assertEqual(0.8, result.model.w_team)
        self.assertEqual(0.1, result.model.indiv_scale_top)
        self.assertEqual(0.4, result.model.indiv_scale_bottom)
        self.assertEqual(2.0, result.model.indiv_clamp_bottom)
        self.assertEqual(25.0, result.model.clamp_top_grid_ref)
        self.assertEqual(0.8, result.metrics["w_team"])
        self.assertEqual(0.1, result.metrics["indiv_scale_top"])
        self.assertEqual(25.0, result.metrics["clamp_top_grid_ref"])

    def test_validation_frame_produces_held_out_metric(self) -> None:
        result = shift_v2.train_shift_v2(self._frame(60, seed=1), val_df=self._frame(40, seed=2))
        self.assertIn("mae_vs_realised_val", result.metrics)
        self.assertEqual(40.0, result.metrics["n_rows_val"])

    def test_no_validation_frame_omits_held_out_metric(self) -> None:
        result = shift_v2.train_shift_v2(self._frame(60, seed=3))
        self.assertNotIn("mae_vs_realised_val", result.metrics)


class ImpactScoreStabilizationTests(TestCase):
    def test_small_cohort_uses_normal_cdf_of_local_zscore(self) -> None:
        from scipy.special import ndtr

        per_player = pd.DataFrame(
            {
                "tournament_id": [1, 1, 1],
                "role": ["tank", "tank", "tank"],
                "player_id": [10, 11, 12],
                "raw_value": [0.3, 0.1, -0.2],
                "impact_score": [100.0, 50.0, 0.0],  # coarse empirical percentile
                "local_zscore": [1.2, 0.0, -0.8],
            }
        )

        out = performance_v2.stabilize_small_cohort_impact(per_player, min_cohort=8)

        expected = ndtr(np.array([1.2, 0.0, -0.8])) * 100.0
        np.testing.assert_allclose(out["impact_score"].to_numpy(), expected, rtol=1e-6)
        # The neutral player lands at ~50 instead of the coarse 50/100/0 ladder.
        self.assertAlmostEqual(50.0, float(out["impact_score"].iloc[1]), places=4)

    def test_large_cohort_keeps_empirical_percentile(self) -> None:
        n = 10
        per_player = pd.DataFrame(
            {
                "tournament_id": [1] * n,
                "role": ["damage"] * n,
                "player_id": list(range(n)),
                "raw_value": np.linspace(-1, 1, n),
                "impact_score": np.linspace(0, 100, n),
                "local_zscore": np.linspace(-2, 2, n),
            }
        )

        out = performance_v2.stabilize_small_cohort_impact(per_player, min_cohort=8)

        # Cohort of 10 >= min_cohort ⇒ empirical impact_score is untouched.
        np.testing.assert_allclose(out["impact_score"].to_numpy(), np.linspace(0, 100, n))

    def test_noop_without_local_zscore(self) -> None:
        per_player = pd.DataFrame(
            {
                "tournament_id": [1, 1],
                "role": ["tank", "tank"],
                "player_id": [1, 2],
                "impact_score": [25.0, 75.0],
            }
        )

        out = performance_v2.stabilize_small_cohort_impact(per_player)

        np.testing.assert_allclose(out["impact_score"].to_numpy(), [25.0, 75.0])


class PerformanceBaselineTests(TestCase):
    def test_logistic_baseline_scales_features(self) -> None:
        frame = pd.DataFrame(
            {
                "team_avg_mu": [900.0, 1200.0, 1500.0, 1800.0],
                "opp_avg_mu": [1800.0, 1500.0, 1200.0, 900.0],
                "mu_gap": [-900.0, -300.0, 300.0, 900.0],
                "won": [0, 0, 1, 1],
            }
        )

        _, baseline = performance_v2.build_target(frame)

        self.assertIn("standardscaler", baseline.named_steps)
        self.assertEqual(
            1000,
            baseline.named_steps["logisticregression"].max_iter,
        )

    def test_single_class_falls_back_to_constant_baseline(self) -> None:
        frame = pd.DataFrame(
            {
                "team_avg_mu": [1500.0, 1600.0],
                "opp_avg_mu": [1600.0, 1500.0],
                "mu_gap": [-100.0, 100.0],
                "won": [1, 1],
            }
        )

        y_perf, baseline = performance_v2.build_target(frame)

        self.assertIsInstance(baseline, performance_v2._ConstantClassifier)
        self.assertEqual(2, len(y_perf))

    def test_target_uses_out_of_fold_probabilities(self) -> None:
        rng = np.random.default_rng(0)
        won = np.array([0] * 20 + [1] * 20)
        mu = np.concatenate([rng.normal(-1.0, 1.0, 20), rng.normal(1.0, 1.0, 20)])
        frame = pd.DataFrame({"team_avg_mu": mu, "opp_avg_mu": -mu, "mu_gap": 2 * mu, "won": won})

        y_perf, baseline = performance_v2.build_target(frame)

        # Reconstruct the expected out-of-fold residual with the same estimator,
        # folds and seed; build_target must match it (i.e. not be in-sample).
        from sklearn.model_selection import StratifiedKFold, cross_val_predict

        X = frame[["team_avg_mu", "opp_avg_mu", "mu_gap"]].to_numpy()
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
        expected_oof = cross_val_predict(
            performance_v2._make_logistic_baseline(),
            X,
            won,
            cv=cv,
            method="predict_proba",
        )[:, 1]

        np.testing.assert_allclose(y_perf.to_numpy(), won - expected_oof, rtol=1e-6)
        # Baseline is still fit on all rows (usable for inference).
        self.assertEqual((40, 2), baseline.predict_proba(X).shape)
