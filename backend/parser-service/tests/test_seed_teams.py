"""P0 pack: tests for seed_teams distribution algorithm."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

stage_service = importlib.import_module("src.services.admin.stage")
enums = importlib.import_module("shared.core.enums")


def _build_stage(*, stage_id: int, tournament_id: int, num_groups: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=stage_id,
        tournament_id=tournament_id,
        stage_type=enums.StageType.ROUND_ROBIN,
        items=[
            SimpleNamespace(
                id=100 + g,
                name=chr(65 + g),
                order=g,
                inputs=[],
            )
            for g in range(num_groups)
        ],
    )


def _team(team_id: int, tournament_id: int, avg_sr: float, total_sr: int | None = None):
    return SimpleNamespace(
        id=team_id,
        tournament_id=tournament_id,
        avg_sr=avg_sr,
        total_sr=total_sr if total_sr is not None else int(avg_sr * 5),
    )


def _mk_session(teams: list) -> SimpleNamespace:
    added_inputs: list = []

    async def fake_execute(_query):
        # Single-purpose stub: the only execute() call in seed_teams is the
        # `SELECT Team WHERE id IN (...)` query. Returning all teams is safe
        # because seed_teams filters them in Python anyway.
        result_mock = Mock()
        scalars_mock = Mock()
        scalars_mock.all.return_value = teams
        result_mock.scalars.return_value = scalars_mock
        return result_mock

    session = SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        add=Mock(side_effect=lambda obj: added_inputs.append(obj)),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )
    session._added_inputs = added_inputs
    return session


class SeedTeamsTests(IsolatedAsyncioTestCase):
    async def test_snake_sr_4_groups_16_teams(self) -> None:
        tournament_id = 99
        stage = _build_stage(stage_id=1, tournament_id=tournament_id, num_groups=4)

        teams = [_team(team_id=i, tournament_id=tournament_id, avg_sr=5000 - i * 50) for i in range(1, 17)]
        session = _mk_session(teams)

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.standings_recalculation, "enqueue_tournament_recalculation", AsyncMock()),
        ):
            await stage_service.seed_teams(session, stage.id, [t.id for t in teams], mode="snake_sr", notify=False)

        # 16 inputs added, all FINAL
        added = session._added_inputs
        self.assertEqual(16, len(added))
        for inp in added:
            self.assertEqual(enums.StageItemInputType.FINAL, inp.input_type)

        # Group A should have the strongest team (id=1, sr=5000) at slot 1.
        group_a_inputs = [inp for inp in added if inp.stage_item_id == 100]
        group_a_inputs.sort(key=lambda i: i.slot)
        self.assertEqual(1, group_a_inputs[0].team_id)

        # Snake: row 0 = A,B,C,D; row 1 = D,C,B,A; row 2 = A,B,C,D; row 3 = D,C,B,A
        # Team 1 (idx 0, row 0) → A
        # Team 2 (idx 1, row 0) → B
        # Team 3 (idx 2, row 0) → C
        # Team 4 (idx 3, row 0) → D
        # Team 5 (idx 4, row 1) → D (reversed column 0 -> 3)
        # Team 6 (idx 5, row 1) → C
        # Team 7 (idx 6, row 1) → B
        # Team 8 (idx 7, row 1) → A
        expected_group_for_team = {
            1: 100,
            2: 101,
            3: 102,
            4: 103,
            5: 103,
            6: 102,
            7: 101,
            8: 100,
            9: 100,
            10: 101,
            11: 102,
            12: 103,
            13: 103,
            14: 102,
            15: 101,
            16: 100,
        }
        for inp in added:
            expected = expected_group_for_team[inp.team_id]
            self.assertEqual(
                expected,
                inp.stage_item_id,
                f"Team {inp.team_id} expected in group {expected}, got {inp.stage_item_id}",
            )

    async def test_snake_sr_balances_group_strength(self) -> None:
        """After snake-seed, sum of avg_sr per group should be within a small
        delta regardless of number of groups."""
        tournament_id = 99
        stage = _build_stage(stage_id=1, tournament_id=tournament_id, num_groups=4)
        teams = [_team(team_id=i, tournament_id=tournament_id, avg_sr=5000 - i * 100) for i in range(1, 17)]
        session = _mk_session(teams)

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.standings_recalculation, "enqueue_tournament_recalculation", AsyncMock()),
        ):
            await stage_service.seed_teams(session, stage.id, [t.id for t in teams], mode="snake_sr", notify=False)

        group_totals: dict[int, float] = {}
        team_by_id = {t.id: t for t in teams}
        for inp in session._added_inputs:
            group_totals.setdefault(inp.stage_item_id, 0.0)
            group_totals[inp.stage_item_id] += team_by_id[inp.team_id].avg_sr

        totals = list(group_totals.values())
        self.assertEqual(4, len(totals))
        spread = max(totals) - min(totals)
        # With strictly linear SR decay, snake-draft guarantees spread ≤ 2*step
        # for even N. Here step=100, so ≤ 200.
        self.assertLessEqual(spread, 200, f"groups unbalanced: {group_totals}")

    async def test_rejects_empty_team_list(self) -> None:
        stage = _build_stage(stage_id=1, tournament_id=99, num_groups=2)
        session = _mk_session([])

        with patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(Exception) as ctx:
                await stage_service.seed_teams(session, stage.id, [], mode="snake_sr")
        self.assertIn("non-empty", str(ctx.exception))

    async def test_rejects_duplicate_team_ids(self) -> None:
        stage = _build_stage(stage_id=1, tournament_id=99, num_groups=2)
        session = _mk_session([])

        with patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(Exception) as ctx:
                await stage_service.seed_teams(session, stage.id, [1, 2, 1, 3], mode="snake_sr")
        self.assertIn("duplicates", str(ctx.exception))

    async def test_rejects_cross_tournament_teams(self) -> None:
        stage = _build_stage(stage_id=1, tournament_id=99, num_groups=2)
        # Team belongs to a different tournament.
        alien_teams = [_team(team_id=1, tournament_id=100, avg_sr=5000)]
        session = _mk_session(alien_teams)

        with patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(Exception) as ctx:
                await stage_service.seed_teams(session, stage.id, [1], mode="snake_sr")
        self.assertIn("do not belong", str(ctx.exception))

    async def test_rejects_stage_without_items(self) -> None:
        stage = SimpleNamespace(
            id=1,
            tournament_id=99,
            stage_type=enums.StageType.ROUND_ROBIN,
            items=[],
        )
        session = _mk_session([])

        with patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(Exception) as ctx:
                await stage_service.seed_teams(session, stage.id, [1, 2], mode="snake_sr")
        self.assertIn("stage_items", str(ctx.exception))

    async def test_uneven_distribution_for_non_multiple(self) -> None:
        """7 teams across 3 groups should distribute as 3, 2, 2 (or similar)."""
        tournament_id = 99
        stage = _build_stage(stage_id=1, tournament_id=tournament_id, num_groups=3)
        teams = [_team(team_id=i, tournament_id=tournament_id, avg_sr=5000 - i * 100) for i in range(1, 8)]
        session = _mk_session(teams)

        with (
            patch.object(stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.standings_recalculation, "enqueue_tournament_recalculation", AsyncMock()),
        ):
            await stage_service.seed_teams(session, stage.id, [t.id for t in teams], mode="snake_sr", notify=False)

        counts: dict[int, int] = {}
        for inp in session._added_inputs:
            counts[inp.stage_item_id] = counts.get(inp.stage_item_id, 0) + 1

        self.assertEqual({2, 3}, set(counts.values()))
