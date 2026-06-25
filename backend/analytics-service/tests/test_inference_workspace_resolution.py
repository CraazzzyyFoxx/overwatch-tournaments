"""``run_for_tournament`` must scope to the tournament's own workspace.

Regression for the CLI-vs-RPC divergence: the CLI (`ml.cli infer/backfill`)
defaults ``workspace_id=None`` while the RPC recalculate job always passes
``job.workspace_id``. With ``None`` the feature cohorts and the effective
division grid are built globally (all workspaces) instead of the tournament's
workspace, so the persisted shift/impact differ from what the UI shows. The fix
resolves ``workspace_id`` from the tournament when it is ``None`` so every entry
point agrees.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

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

runner = importlib.import_module("src.services.ml.inference.runner")

# Only kinds backed by module-level functions in ``runner`` — avoids the lazy
# ``match_quality_runner`` import and the player-anomaly path.
KINDS = ["performance", "shift", "standings"]


class RunForTournamentWorkspaceResolutionTests(IsolatedAsyncioTestCase):
    async def test_resolves_workspace_from_tournament_when_none(self) -> None:
        session = SimpleNamespace()

        with (
            patch.object(
                runner,
                "get_tournament_workspace_id",
                AsyncMock(return_value=1),
            ) as resolve,
            patch.object(
                runner, "run_performance_for_tournament", AsyncMock(return_value=0)
            ) as perf,
            patch.object(
                runner, "run_shift_for_tournament", AsyncMock(return_value=0)
            ) as shift,
            patch.object(
                runner, "run_standings_for_tournament", AsyncMock(return_value=0)
            ) as standings,
        ):
            await runner.run_for_tournament(
                session, 7, workspace_id=None, model_kinds=KINDS
            )

        resolve.assert_awaited_once_with(session, 7)
        for sub in (perf, shift, standings):
            self.assertEqual(1, sub.await_args.kwargs["workspace_id"])

    async def test_keeps_explicit_workspace_id_untouched(self) -> None:
        session = SimpleNamespace()

        with (
            patch.object(
                runner, "get_tournament_workspace_id", AsyncMock()
            ) as resolve,
            patch.object(
                runner, "run_performance_for_tournament", AsyncMock(return_value=0)
            ) as perf,
            patch.object(
                runner, "run_shift_for_tournament", AsyncMock(return_value=0)
            ) as shift,
            patch.object(
                runner, "run_standings_for_tournament", AsyncMock(return_value=0)
            ) as standings,
        ):
            await runner.run_for_tournament(
                session, 7, workspace_id=2, model_kinds=KINDS
            )

        resolve.assert_not_awaited()
        for sub in (perf, shift, standings):
            self.assertEqual(2, sub.await_args.kwargs["workspace_id"])
