from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

analytics_flows = importlib.import_module("src.services.analytics_read.flows")

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _tournament() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        created_at=NOW,
        updated_at=None,
        number=7,
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
        sub_role="hitscan",
        rank=rank,
        role="Damage",
        tournament_id=7,
        user_id=player_id + 1000,
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
    confidence: float = 0.82,
) -> SimpleNamespace:
    return SimpleNamespace(
        shift=value,
        confidence=confidence,
        effective_evidence=2.4,
        sample_tournaments=4,
        sample_matches=9,
        log_coverage=0.5,
    )


class AnalyticsFlowsTests(IsolatedAsyncioTestCase):
    async def test_get_analytics_serializes_enriched_fields(self) -> None:
        session = SimpleNamespace()
        algorithm = SimpleNamespace(id=11)
        team = _team()
        player = _player()
        analytics = _analytics(wins=4, losses=1, shift_one=200)
        shift = _shift(value=1.6, confidence=0.82)

        with (
            patch.object(analytics_flows.service, "get_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(
                analytics_flows.service,
                "get_analytics",
                AsyncMock(return_value=[(team, player, shift, analytics)]),
            ),
            patch.object(
                analytics_flows.service,
                "get_predicted_places",
                AsyncMock(return_value={team.id: 3}),
            ),
            patch.object(
                analytics_flows.service,
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
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=None)),
        ):
            result = await analytics_flows.get_analytics(session, tournament_id=7, algorithm_id=11)

        serialized_team = result.teams[0]
        serialized_player = serialized_team.players[0]

        self.assertEqual(4, serialized_team.wins)
        self.assertEqual(1, serialized_team.losses)
        self.assertEqual(3, serialized_team.predicted_place)
        self.assertEqual(2, serialized_team.placement_delta)
        self.assertEqual(200, serialized_team.manual_shift_points)
        self.assertEqual(0.2, serialized_team.manual_shift)
        self.assertEqual(0.82, serialized_team.avg_confidence)
        self.assertEqual("smurf", serialized_team.anomalies[0].kind)
        self.assertEqual("smurf", serialized_player.anomalies[0].kind)
        self.assertEqual("promote", serialized_player.predicted_direction)
        self.assertEqual(-2, serialized_player.predicted_delta)
        self.assertEqual(0.82, serialized_player.confidence)
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
            patch.object(analytics_flows.service, "get_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(
                analytics_flows.service,
                "get_analytics",
                AsyncMock(return_value=[(team, player, _shift(), _analytics())]),
            ),
            patch.object(analytics_flows.service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(
                analytics_flows.service,
                "get_match_quality_anomalies",
                AsyncMock(return_value=[]),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=None)),
        ):
            result = await analytics_flows.get_analytics(session, tournament_id=7, algorithm_id=11)

        self.assertEqual(2, result.teams[0].placement)

    async def test_get_analytics_uses_empty_fallbacks_for_optional_v2_data(self) -> None:
        session = SimpleNamespace()
        algorithm = SimpleNamespace(id=11)
        team = _team()
        player = _player(is_newcomer=True)

        with (
            patch.object(analytics_flows.service, "get_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(
                analytics_flows.service,
                "get_analytics",
                AsyncMock(return_value=[(team, player, _shift(), _analytics())]),
            ),
            patch.object(analytics_flows.service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(
                analytics_flows.service,
                "get_match_quality_anomalies",
                AsyncMock(return_value=[]),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=None)),
        ):
            result = await analytics_flows.get_analytics(session, tournament_id=7, algorithm_id=11)

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
                analytics_flows.service,
                "get_algorithm",
                AsyncMock(return_value=algorithm),
            ),
            patch.object(
                analytics_flows.service,
                "get_analytics",
                AsyncMock(return_value=[]),
            ) as get_analytics,
            patch.object(analytics_flows.service, "get_predicted_places", AsyncMock(return_value={})),
            patch.object(
                analytics_flows.service,
                "get_match_quality_anomalies",
                AsyncMock(return_value=[]),
            ),
            patch.object(analytics_flows, "get_division_grid", AsyncMock(return_value=None)),
        ):
            await analytics_flows.get_analytics(
                session,
                tournament_id=7,
                algorithm_id=11,
                workspace_id=5,
            )

        get_analytics.assert_awaited_once_with(session, 7, algorithm, workspace_id=5)


class PredictPlayerDivisionTests(IsolatedAsyncioTestCase):
    """The forecast must always agree with the displayed Signal (``points``):
    direction is the sign of the signal (no hidden dead-zone that shows "flat"
    for a non-zero Signal), while the predicted-division magnitude rounds it."""

    @staticmethod
    def _player(division: int | None = 10) -> SimpleNamespace:
        return SimpleNamespace(division=division)

    async def test_direction_follows_signal_sign(self) -> None:
        predict = analytics_flows._predict_player_division
        # +0.7 → one-division promote.
        _, direction, delta = predict(self._player(), points=0.7)
        self.assertEqual("promote", direction)
        self.assertEqual(-1, delta)
        # Negative → demote.
        _, d_neg, delta_neg = predict(self._player(), points=-0.7)
        self.assertEqual("demote", d_neg)
        self.assertEqual(1, delta_neg)
        # Exactly zero → flat.
        _, d_zero, delta_zero = predict(self._player(), points=0.0)
        self.assertEqual("flat", d_zero)
        self.assertEqual(0, delta_zero)

    async def test_sub_half_signal_still_leans_not_flat(self) -> None:
        # The reported desync: a +0.4 Signal must NOT show a "flat" forecast.
        # Direction leans promote; the predicted division holds (rounds to 0).
        predict = analytics_flows._predict_player_division
        _, direction, delta = predict(self._player(), points=0.4)
        self.assertEqual("promote", direction)
        self.assertEqual(0, delta)
        _, d_neg, delta_neg = predict(self._player(), points=-0.4)
        self.assertEqual("demote", d_neg)
        self.assertEqual(0, delta_neg)

    async def test_clamped_to_three_divisions(self) -> None:
        predict = analytics_flows._predict_player_division
        div, direction, delta = predict(self._player(20), points=9.0)
        self.assertEqual("promote", direction)
        self.assertEqual(-3, delta)
        self.assertEqual(17, div)
