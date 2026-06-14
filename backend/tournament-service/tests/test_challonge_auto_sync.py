"""Tests for the background Challonge auto-sync (pull) orchestration.

Covers ``sync_active_challonge_tournaments`` (the worker job) and the
``_import_cache_invalidation_reason`` helper that decides which ``tournament_changed`` reason an
import should emit so the read cache is invalidated consistently.

The heavy ``import_tournament`` and the active-tournament selector are mocked — these tests assert
orchestration (no-op gates, per-tournament isolation, aggregation), not Challonge I/O.
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
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

challonge_sync = importlib.import_module("src.services.challonge.sync")


class _FakeSessionCtx:
    """Minimal async-context-manager wrapper so ``session_factory()`` works in the job."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _session_factory() -> object:
    return _FakeSessionCtx(SimpleNamespace())


def _settings(*, enabled: bool = True, username: str = "user", api_key: str = "key") -> SimpleNamespace:
    return SimpleNamespace(
        challonge_auto_sync_enabled=enabled,
        challonge_username=username,
        challonge_api_key=api_key,
    )


class CacheInvalidationReasonTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _stats(**overrides: int) -> dict:
        base = {
            "created": 0,
            "updated": 0,
            "matches_synced": 0,
            "stages_created": 0,
            "groups_created": 0,
            "stage_inputs_created": 0,
            "bracket_links_created": 0,
            "bracket_links_updated": 0,
        }
        base.update(overrides)
        return base

    async def test_no_change_returns_none(self) -> None:
        self.assertIsNone(challonge_sync._import_cache_invalidation_reason(self._stats()))

    async def test_results_change_when_only_matches(self) -> None:
        self.assertEqual(
            challonge_sync._import_cache_invalidation_reason(self._stats(matches_synced=3, updated=2)),
            "results_changed",
        )

    async def test_structure_change_takes_precedence(self) -> None:
        self.assertEqual(
            challonge_sync._import_cache_invalidation_reason(self._stats(matches_synced=3, stages_created=1)),
            "structure_changed",
        )
        self.assertEqual(
            challonge_sync._import_cache_invalidation_reason(self._stats(bracket_links_updated=1)),
            "structure_changed",
        )


class SyncActiveChallongeTournamentsTests(IsolatedAsyncioTestCase):
    async def test_no_op_when_disabled(self) -> None:
        with patch.object(challonge_sync.config, "settings", _settings(enabled=False)):
            with (
                patch.object(challonge_sync, "list_active_challonge_tournament_ids", AsyncMock()) as selector,
                patch.object(challonge_sync, "import_tournament", AsyncMock()) as importer,
            ):
                result = await challonge_sync.sync_active_challonge_tournaments(_session_factory)

        self.assertEqual(result, [])
        selector.assert_not_awaited()
        importer.assert_not_awaited()

    async def test_no_op_when_credentials_missing(self) -> None:
        with patch.object(challonge_sync.config, "settings", _settings(api_key="")):
            with (
                patch.object(challonge_sync, "list_active_challonge_tournament_ids", AsyncMock()) as selector,
                patch.object(challonge_sync, "import_tournament", AsyncMock()) as importer,
                patch.object(challonge_sync.logger, "warning") as warn,
            ):
                result = await challonge_sync.sync_active_challonge_tournaments(_session_factory)

        self.assertEqual(result, [])
        selector.assert_not_awaited()
        importer.assert_not_awaited()
        warn.assert_called_once()

    async def test_imports_each_active_tournament_and_aggregates(self) -> None:
        stats = {"created": 1, "updated": 2, "conflicts": 0, "errors": 0, "matches_synced": 3}
        with patch.object(challonge_sync.config, "settings", _settings()):
            with (
                patch.object(
                    challonge_sync,
                    "list_active_challonge_tournament_ids",
                    AsyncMock(return_value=[10, 20]),
                ),
                patch.object(challonge_sync, "import_tournament", AsyncMock(return_value=stats)) as importer,
            ):
                result = await challonge_sync.sync_active_challonge_tournaments(_session_factory)

        self.assertEqual(importer.await_count, 2)
        self.assertEqual([r["tournament_id"] for r in result], [10, 20])
        self.assertTrue(all(r["status"] == "success" for r in result))
        self.assertEqual(result[0]["matches_synced"], 3)
        self.assertEqual(result[0]["updated"], 2)

    async def test_one_failure_does_not_abort_others(self) -> None:
        async def _import(_session: object, tournament_id: int) -> dict:
            if tournament_id == 20:
                raise RuntimeError("challonge boom")
            return {"created": 0, "updated": 1, "conflicts": 0, "errors": 0, "matches_synced": 1}

        with patch.object(challonge_sync.config, "settings", _settings()):
            with (
                patch.object(
                    challonge_sync,
                    "list_active_challonge_tournament_ids",
                    AsyncMock(return_value=[10, 20, 30]),
                ),
                patch.object(challonge_sync, "import_tournament", AsyncMock(side_effect=_import)),
                patch.object(challonge_sync.logger, "exception"),
            ):
                result = await challonge_sync.sync_active_challonge_tournaments(_session_factory)

        by_id = {r["tournament_id"]: r for r in result}
        self.assertEqual(by_id[10]["status"], "success")
        self.assertEqual(by_id[30]["status"], "success")
        self.assertEqual(by_id[20]["status"], "failed")
        self.assertIn("challonge boom", by_id[20]["error"])
