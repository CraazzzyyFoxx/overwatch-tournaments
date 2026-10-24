from __future__ import annotations

import importlib
from datetime import UTC, datetime
from statistics import NormalDist
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from shared.division_grid import DEFAULT_GRID, DivisionGrid, DivisionTier
from shared.schemas.role import RoleRef
from src.domain.forecast import predict_player_division

analytics_flows = importlib.import_module("src.services.analytics.reads")

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _tournament() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        created_at=NOW,
        updated_at=None,
        name="Tournament 7",
        is_finished=False,
        division_grid_version_id=None,
    )


def _team(
    *,
    team_id: int = 99,
    name: str = "Alpha",
    avg_sr: int = 2000,
    placement: int | None = 1,
) -> SimpleNamespace:
    standings = []
    if placement is not None:
        standings.append(SimpleNamespace(overall_position=placement, group=None))
    return SimpleNamespace(
        id=team_id,
        created_at=NOW,
        updated_at=None,
        name=name,
        image_url=None,
        avg_sr=avg_sr,
        total_sr=avg_sr * 5,
        captain_id=1,
        tournament_id=7,
        tournament=_tournament(),
        standings=standings,
    )


def _player(
    *,
    player_id: int = 42,
    team_id: int = 99,
    rank: int = 800,
    is_newcomer: bool = False,
    is_newcomer_role: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=player_id,
        created_at=NOW,
        updated_at=None,
        name=f"Player {player_id}",
        rank=rank,
        role_ref=RoleRef(dimension="player_role", role="damage_hitscan", parent="damage"),
        tournament_id=7,
        # Player.user_id was dropped in the contract step (iwrefac07); the
        # identity anchor is workspace_member.player_id instead.
        workspace_member=SimpleNamespace(player_id=player_id + 1000),
        team_id=team_id,
        is_newcomer=is_newcomer,
        is_newcomer_role=is_newcomer_role,
        is_substitution=False,
        related_player_id=None,
    )


def _analytics(
    *,
    wins: int = 4,
    losses: int = 1,
    shift_one: int | None = 100,
    shift_two: int | None = 50,
    shift: int | None = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        shift_one=shift_one,
        shift_two=shift_two,
        wins=wins,
        losses=losses,
        shift=shift,
    )


def _shift(
    *,
    value: float = 1.25,
    sd: float | None = 0.01,
) -> SimpleNamespace:
    return SimpleNamespace(
        shift=value,
        shift_sd=sd,
        effective_evidence=2.4,
        sample_tournaments=4,
        sample_matches=9,
        log_coverage=0.5,
    )


class AnalyticsFlowsTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.object(analytics_flows, "tournament_discipline", AsyncMock(return_value="overwatch"))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_stored_predictions_are_not_served_to_a_discipline_without_analytics(self) -> None:
        reader = AsyncMock(return_value=SimpleNamespace(id=11))
        with (
            patch.object(analytics_flows, "tournament_discipline", AsyncMock(return_value="lol")),
            patch.object(analytics_flows.analytics_read_service, "get_algorithm", reader),
            patch.object(analytics_flows.analytics_read_service, "get_analytics", AsyncMock()) as rows,
            self.assertRaises(analytics_flows.errors.ApiHTTPException) as raised,
        ):
            await analytics_flows.flows_service.get_analytics(SimpleNamespace(), tournament_id=7, algorithm_id=11)

        self.assertEqual(404, raised.exception.status_code)
        rows.assert_not_awaited()

    async def _read(self, rows: list) -> analytics_flows.schemas.TournamentAnalytics:
        service = analytics_flows.analytics_read_service
        with (
            patch.object(service, "get_algorithm", AsyncMock(return_value=SimpleNamespace(id=11))),
            patch.object(service, "get_analytics", AsyncMock(return_value=rows)),
            patch.object(service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(service, "get_match_quality_anomalies", AsyncMock(return_value=[])),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=DEFAULT_GRID)),
        ):
            return await analytics_flows.flows_service.get_analytics(
                SimpleNamespace(), tournament_id=7, algorithm_id=11
            )

    async def test_team_row_sums_forecasts_and_compares_rosters_on_the_canonical_ladder(self) -> None:
        rank = DEFAULT_GRID.resolve_rank_from_division
        strong, weak = _team(team_id=1, name="Strong"), _team(team_id=2, name="Weak")
        rows = [
            (strong, _player(player_id=1, team_id=1, rank=rank(10)), _shift(value=2.0), _analytics(shift_one=200)),
            (strong, _player(player_id=2, team_id=1, rank=rank(12)), _shift(value=-1.0), _analytics(shift_one=-50)),
            (weak, _player(player_id=3, team_id=2, rank=rank(20)), _shift(value=0.0), _analytics(shift_one=None)),
            (weak, _player(player_id=4, team_id=2, rank=rank(22)), _shift(value=0.0), _analytics(shift_one=None)),
        ]

        teams = {team.id: team for team in (await self._read(rows)).teams}

        # Two divisions up and one down: the team forecast climbs one tournament-grid division.
        self.assertEqual(1, teams[1].total_shift)
        self.assertEqual(0, teams[2].total_shift)
        # Mean canonical divisions 11 and 21 against a field mean of 16; stronger than the field reads negative.
        self.assertEqual(-5.0, teams[1].balancer_shift)
        self.assertEqual(5.0, teams[2].balancer_shift)
        # Σ move_1 = 150 canonical points = 1.5 divisions.
        self.assertEqual(150, teams[1].manual_shift_points)
        self.assertEqual(1.5, teams[1].manual_shift)

    async def test_forecast_threshold_is_read_from_settings(self) -> None:
        # P(m ≥ 1.5) for m ~ N(1.4, 0.5²) is Φ(−0.2) ≈ 0.42: a two-division climb only below that gate.
        player = _player(rank=DEFAULT_GRID.resolve_rank_from_division(20))
        rows = [(_team(), player, _shift(value=1.4, sd=0.5), _analytics())]

        self.assertEqual(-1, (await self._read(rows)).teams[0].players[0].predicted_delta)
        with patch.object(analytics_flows.settings, "forecast_confidence_threshold", 0.4):
            self.assertEqual(-2, (await self._read(rows)).teams[0].players[0].predicted_delta)

    async def test_get_analytics_serializes_enriched_fields(self) -> None:
        session = SimpleNamespace()
        algorithm = SimpleNamespace(id=11)
        team = _team()
        player = _player()
        analytics = _analytics(wins=4, losses=1, shift_one=200)
        shift = _shift(value=1.6, sd=0.1)

        with (
            patch.object(analytics_flows.analytics_read_service, "get_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_analytics",
                AsyncMock(return_value=[(team, player, shift, analytics)]),
            ),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_predicted_places",
                AsyncMock(return_value={team.id: 3}),
            ),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_match_quality_anomalies",
                AsyncMock(
                    return_value=[
                        (
                            501,
                            [
                                {
                                    "player_id": player.id,
                                    "kind": "smurf",
                                    "score": 0.71,
                                    "reasons": ["impact above cohort"],
                                }
                            ],
                        )
                    ]
                ),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=DEFAULT_GRID)),
        ):
            result = await analytics_flows.flows_service.get_analytics(session, tournament_id=7, algorithm_id=11)

        serialized_team = result.teams[0]
        serialized_player = serialized_team.players[0]

        self.assertEqual(4, serialized_team.wins)
        self.assertEqual(1, serialized_team.losses)
        self.assertEqual(3, serialized_team.predicted_place)
        self.assertEqual(2, serialized_team.placement_delta)
        self.assertEqual(200, serialized_team.manual_shift_points)
        self.assertEqual(2.0, serialized_team.manual_shift)
        self.assertEqual(2, serialized_team.total_shift)
        self.assertEqual(0.8413, serialized_team.avg_confidence)
        self.assertEqual("smurf", serialized_team.anomalies[0].kind)
        self.assertEqual("smurf", serialized_player.anomalies[0].kind)
        self.assertEqual("promote", serialized_player.predicted_direction)
        self.assertEqual(-2, serialized_player.predicted_delta)
        # P(m ≥ 1.5) for m ~ N(1.6, 0.1²): the probability of the shown two-division climb.
        self.assertAlmostEqual(NormalDist().cdf(1.0), serialized_player.confidence)
        self.assertEqual(2.4, serialized_player.effective_evidence)
        self.assertEqual(4, serialized_player.sample_tournaments)
        self.assertEqual(9, serialized_player.sample_matches)
        self.assertEqual(0.5, serialized_player.log_coverage)
        self.assertEqual(1, result.summary.total_teams)
        self.assertEqual(1, result.summary.total_players)
        self.assertEqual(1, result.summary.anomaly_count)
        self.assertEqual(1, result.summary.manual_shift_team_count)
        self.assertEqual(2.0, result.summary.avg_placement_delta)

    async def test_get_analytics_uses_best_positive_team_placement(self) -> None:
        session = SimpleNamespace()
        algorithm = SimpleNamespace(id=11)
        team = _team(placement=None)
        team.standings = [
            SimpleNamespace(overall_position=0, group=None),
            SimpleNamespace(overall_position=2, group=None),
        ]
        player = _player()

        with (
            patch.object(analytics_flows.analytics_read_service, "get_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_analytics",
                AsyncMock(return_value=[(team, player, _shift(), _analytics())]),
            ),
            patch.object(analytics_flows.analytics_read_service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_match_quality_anomalies",
                AsyncMock(return_value=[]),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=DEFAULT_GRID)),
        ):
            result = await analytics_flows.flows_service.get_analytics(session, tournament_id=7, algorithm_id=11)

        self.assertEqual(2, result.teams[0].placement)

    async def test_get_analytics_uses_empty_fallbacks_for_optional_v2_data(self) -> None:
        session = SimpleNamespace()
        algorithm = SimpleNamespace(id=11)
        team = _team()
        player = _player(is_newcomer=True)

        with (
            patch.object(analytics_flows.analytics_read_service, "get_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_analytics",
                AsyncMock(return_value=[(team, player, _shift(), _analytics())]),
            ),
            patch.object(analytics_flows.analytics_read_service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_match_quality_anomalies",
                AsyncMock(return_value=[]),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=DEFAULT_GRID)),
        ):
            result = await analytics_flows.flows_service.get_analytics(session, tournament_id=7, algorithm_id=11)

        self.assertIsNone(result.teams[0].predicted_place)
        self.assertIsNone(result.teams[0].placement_delta)
        self.assertEqual([], result.teams[0].anomalies)
        self.assertEqual([], result.teams[0].players[0].anomalies)
        self.assertEqual(1, result.summary.newcomer_count)

    async def test_get_analytics_passes_workspace_scope_to_service_layer(self) -> None:
        session = SimpleNamespace()
        algorithm = SimpleNamespace(id=11)

        with (
            patch.object(
                analytics_flows.analytics_read_service,
                "get_algorithm",
                AsyncMock(return_value=algorithm),
            ),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_analytics",
                AsyncMock(return_value=[]),
            ) as get_analytics,
            patch.object(analytics_flows.analytics_read_service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(
                analytics_flows.analytics_read_service,
                "get_match_quality_anomalies",
                AsyncMock(return_value=[]),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=DEFAULT_GRID)),
        ):
            await analytics_flows.flows_service.get_analytics(
                session,
                tournament_id=7,
                algorithm_id=11,
                workspace_id=5,
            )

        get_analytics.assert_awaited_once_with(session, 7, algorithm, workspace_id=5)


def _grid(tiers: int) -> DivisionGrid:
    """A grid of ``tiers`` 100-wide tiers on a rank scale of its own (no native ranges), top tier first."""
    return DivisionGrid(
        version_id=99,
        tiers=tuple(
            DivisionTier(
                id=None,
                slug=None,
                number=number,
                name=f"Tier {number}",
                rank_min=(tiers - number) * 100,
                rank_max=None if number == 1 else (tiers - number) * 100 + 99,
                icon_url="",
            )
            for number in range(1, tiers + 1)
        ),
    )


TIGHT = 1e-6  # an sd small enough to make the forecast a step function of the estimate


class PredictPlayerDivisionTests(TestCase):
    """The player's mis-rating is N(shift, shift_sd²) in canonical-ladder divisions. The shown move is the largest
    k ≤ 3 that is at least 80% certain, its confidence the probability of the shown outcome; the forecast lands on a
    tier of the tournament's own grid."""

    @staticmethod
    def _predict(
        division: int,
        shift: float,
        sd: float | None = TIGHT,
        grid: DivisionGrid = DEFAULT_GRID,
        threshold: float = 0.8,
    ):
        rank = grid.resolve_rank_from_division(division)
        return predict_player_division(rank, grid, shift, sd, threshold=threshold)

    def test_a_tight_estimate_moves_at_the_half_division_boundaries(self) -> None:
        for shift, delta in {0.49: 0, 0.51: -1, 1.49: -1, 1.51: -2, 2.49: -2, 2.51: -3, 9.0: -3}.items():
            self.assertEqual(delta, self._predict(20, shift)[2], msg=f"shift={shift}")
            self.assertEqual(-delta, self._predict(20, -shift)[2], msg=f"shift={-shift}")

    def test_a_wide_estimate_holds_with_low_confidence(self) -> None:
        division, direction, delta, confidence = self._predict(10, 1.2, sd=3.0)
        estimate = NormalDist(1.2, 3.0)
        self.assertEqual((10, "flat", 0), (division, direction, delta))
        self.assertAlmostEqual(estimate.cdf(0.5) - estimate.cdf(-0.5), confidence)
        self.assertLess(confidence, 0.5)

    def test_the_move_is_the_largest_one_that_certain(self) -> None:
        # P(m ≥ 1.5) = Φ(0.7) ≈ 0.76 < 0.8 ≤ P(m ≥ 0.5) = Φ(1.7): one division, not the rounded two.
        division, direction, delta, confidence = self._predict(20, 2.2, sd=1.0)
        self.assertEqual((19, "promote", -1), (division, direction, delta))
        self.assertAlmostEqual(NormalDist().cdf(1.7), confidence)
        self.assertEqual((21, "demote", 1), self._predict(20, -2.2, sd=1.0)[:3])

    def test_hold_confidence_is_the_chance_of_belonging_in_the_current_division(self) -> None:
        division, direction, delta, confidence = self._predict(10, 0.0, sd=0.5)
        self.assertEqual((10, "flat", 0), (division, direction, delta))
        self.assertAlmostEqual(NormalDist().cdf(1.0) - NormalDist().cdf(-1.0), confidence)

    def test_a_row_without_an_sd_holds_with_zero_confidence(self) -> None:
        self.assertEqual((10, "flat", 0, 0.0), self._predict(10, 2.9, sd=None))

    def test_a_zero_sd_is_certain(self) -> None:
        self.assertEqual((9, "promote", -1, 1.0), self._predict(10, 0.6, sd=0.0))

    def test_the_threshold_gates_the_move(self) -> None:
        # P(m ≥ 1.5) = Φ(−0.2) ≈ 0.42.
        self.assertEqual(-1, self._predict(20, 1.4, sd=0.5)[2])
        self.assertEqual(-2, self._predict(20, 1.4, sd=0.5, threshold=0.4)[2])

    def test_unranked_player_has_no_division(self) -> None:
        predicted = predict_player_division(None, DEFAULT_GRID, 2.0, TIGHT, threshold=0.8)
        self.assertEqual((None, "promote", 0), predicted[:3])

    def test_non_default_grid_moves_on_the_canonical_ladder(self) -> None:
        # 23 tiers spread over the 45 canonical divisions: tier n sits at canonical 2n - 1, so a two-division
        # shift is one tier, not two.
        grid = _grid(23)
        self.assertEqual((9, "promote", -1), self._predict(10, 2.0, grid=grid)[:3])
        self.assertEqual((11, "demote", 1), self._predict(10, -2.0, grid=grid)[:3])
        # Canonical 16 is equidistant from tiers 9 (17) and 8 (15): the tie moves past the half-way point.
        self.assertEqual((8, "promote", -2), self._predict(10, 3.0, grid=grid)[:3])

    def test_forecast_stays_inside_the_grid(self) -> None:
        self.assertEqual((45, "demote", 1), self._predict(44, -3.0)[:3])
        self.assertEqual((1, "promote", -1), self._predict(2, 3.0)[:3])
        coarse = _grid(5)  # tiers at canonical 1, 12, 23, 34, 45
        self.assertEqual((5, "demote", 0), self._predict(5, -3.0, grid=coarse)[:3])
        self.assertEqual((1, "promote", 0), self._predict(1, 3.0, grid=coarse)[:3])
