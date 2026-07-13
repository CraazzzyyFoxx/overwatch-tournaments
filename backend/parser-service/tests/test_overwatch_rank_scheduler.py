from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "x")
os.environ.setdefault("CHALLONGE_API_KEY", "x")

scheduler = importlib.import_module("src.services.overwatch_rank.scheduler")
service = importlib.import_module("src.services.overwatch_rank.service")

from shared.core import enums  # noqa: E402
from shared.schemas.settings import RankCollectionConfig  # noqa: E402


class ComputePerTickTests(TestCase):
    """Self-pacing: how many tags to claim per tick."""

    def _call(self, total, *, interval=900, tick=60, rate=30, batch=50, max_per_tick=None):
        return scheduler.compute_per_tick(
            total,
            interval_seconds=interval,
            tick_seconds=tick,
            rate_limit_per_minute=rate,
            batch_size=batch,
            max_per_tick=max_per_tick,
        )

    def test_small_population_claims_at_least_one(self) -> None:
        self.assertEqual(self._call(0), 1)
        self.assertEqual(self._call(5), 1)

    def test_population_within_budget_covers_in_one_interval(self) -> None:
        # 300 tags, 900s interval, 60s tick -> exactly 20/tick, under the 30/min budget.
        limit = self._call(300)
        self.assertEqual(limit, 20)
        # Coverage time equals the configured interval (full population once).
        coverage_seconds = (300 / limit) * 60
        self.assertLessEqual(coverage_seconds, 900)

    def test_population_above_rate_budget_clamps_to_budget(self) -> None:
        # 5000 tags would need 334/tick; the 30/min rate budget caps it at 30.
        self.assertEqual(self._call(5000), 30)

    def test_batch_size_caps_below_rate_budget(self) -> None:
        self.assertEqual(self._call(5000, rate=1000, batch=15), 15)

    def test_max_per_tick_caps_everything(self) -> None:
        self.assertEqual(self._call(5000, rate=1000, batch=50, max_per_tick=10), 10)

    def test_never_exceeds_caps(self) -> None:
        for total in (0, 1, 100, 999, 100_000):
            limit = self._call(total, rate=120, batch=40, max_per_tick=25)
            self.assertGreaterEqual(limit, 1)
            self.assertLessEqual(limit, 25)  # min(batch, max_per_tick, rate_budget)


class JitteredIntervalTests(TestCase):
    def test_zero_fraction_returns_base_exactly(self) -> None:
        self.assertEqual(service._jittered_interval(900, 0.0), 900.0)
        self.assertEqual(service._jittered_interval(900, -1.0), 900.0)

    def test_positive_fraction_stays_within_window(self) -> None:
        base, frac = 900, 0.15
        samples = [service._jittered_interval(base, frac) for _ in range(2000)]
        self.assertTrue(all(base <= s <= base * (1 + frac) for s in samples))
        mean = sum(samples) / len(samples)
        # Expected mean is base*(1 + frac/2); allow generous slack for randomness.
        self.assertAlmostEqual(mean, base * (1 + frac / 2), delta=base * frac * 0.1)


class SelectAndClaimLeaseTests(IsolatedAsyncioTestCase):
    """The claim lease is the dropped-message recovery path; it must be jittered."""

    def _session(self, rows):
        result = SimpleNamespace(all=lambda: rows)
        return SimpleNamespace(scalars=AsyncMock(return_value=result))

    async def test_lease_is_jittered_within_window(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [SimpleNamespace(id=i, next_eligible_at=None) for i in range(50)]
        session = self._session(rows)

        returned = await service.select_and_claim_due(
            session,
            limit=50,
            scope="all",
            interval_seconds=900,
            jitter_fraction=0.2,
            now=now,
        )

        self.assertEqual(len(returned), 50)
        low, high = now + timedelta(seconds=900), now + timedelta(seconds=900 * 1.2)
        for row in rows:
            self.assertGreaterEqual(row.next_eligible_at, low)
            self.assertLessEqual(row.next_eligible_at, high)
        # Jitter must actually spread the batch, not assign one shared instant.
        self.assertGreater(len({r.next_eligible_at for r in rows}), 1)

    async def test_zero_jitter_is_exact_recurrence(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [SimpleNamespace(id=i, next_eligible_at=None) for i in range(5)]
        session = self._session(rows)

        await service.select_and_claim_due(
            session,
            limit=5,
            scope="all",
            interval_seconds=900,
            jitter_fraction=0.0,
            now=now,
        )
        for row in rows:
            self.assertEqual(row.next_eligible_at, now + timedelta(seconds=900))


class RecordFailureTransientTests(IsolatedAsyncioTestCase):
    """Transient upstream failures back off but must never auto-disable a tag."""

    def _session(self, state):
        return SimpleNamespace(scalar=AsyncMock(return_value=state), flush=AsyncMock())

    def _state(self, *, consecutive_failures=0):
        return SimpleNamespace(
            consecutive_failures=consecutive_failures,
            priority_tier=0,
            status=None,
            next_eligible_at="unset",
            last_checked_at=None,
            last_error=None,
            last_success_at=None,
        )

    async def _run(self, *, transient, consecutive_failures):
        cfg = RankCollectionConfig()  # max_consecutive_failures=5, backoff_base_seconds=60
        state = self._state(consecutive_failures=consecutive_failures)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        await service.record_failure(
            self._session(state),
            social_account_id=1,
            battle_tag="Name#1234",
            status=enums.RankCollectionStatus.error,
            error="OverFast 502 for Name-1234",
            config=cfg,
            transient=transient,
            now=now,
        )
        return state, now

    async def test_transient_at_threshold_does_not_disable(self) -> None:
        # 4 prior + this one = 5 = max_consecutive_failures. Permanent would disable here.
        state, _ = await self._run(transient=True, consecutive_failures=4)
        self.assertEqual(state.consecutive_failures, 5)
        self.assertEqual(state.status, enums.RankCollectionStatus.error.value)
        self.assertNotEqual(state.status, enums.RankCollectionStatus.disabled.value)
        self.assertNotIn(state.next_eligible_at, (None, "unset"))

    async def test_permanent_at_threshold_disables(self) -> None:
        state, _ = await self._run(transient=False, consecutive_failures=4)
        self.assertEqual(state.status, enums.RankCollectionStatus.disabled.value)
        self.assertIsNone(state.next_eligible_at)

    async def test_transient_backoff_is_capped(self) -> None:
        # A long outage drives failures high; exponent is capped and backoff
        # clamps to MAX_BACKOFF_SECONDS (no overflow, no disable).
        state, now = await self._run(transient=True, consecutive_failures=999)
        self.assertNotEqual(state.status, enums.RankCollectionStatus.disabled.value)
        self.assertEqual(state.next_eligible_at, now + timedelta(seconds=service.MAX_BACKOFF_SECONDS))


class CollectionStatsAssemblyTests(IsolatedAsyncioTestCase):
    """get_collection_stats merges DB aggregates + config into the dashboard shape."""

    async def test_assembles_rates_tiers_and_validates(self) -> None:
        from unittest.mock import patch

        from src.schemas.admin.rank_collection import RankCollectionStats
        from src.services.overwatch_rank import admin

        raw = {
            "total": 100,
            "never_checked": 5,
            "by_status": {"ok": 60, "disabled": 10, "error": 30},
            "by_tier": {0: 90, 2: 10},  # tier 1 absent -> defaults to 0
            "last_success_at": None,
            "coverage_24h": 40,
            "coverage_7d": 70,
            "fetch_24h": {"ok": 70, "error": 20, "rate_limited": 10},
        }
        cfg = RankCollectionConfig(enabled=True, scope="all")
        with (
            patch.object(admin.service, "collection_stats", AsyncMock(return_value=raw)),
            patch.object(admin.settings_provider, "get_rank_collection_config", AsyncMock(return_value=cfg)),
        ):
            result = await admin.get_collection_stats(object())

        self.assertEqual((result["tier0"], result["tier1"], result["tier2"]), (90, 0, 10))
        self.assertEqual(result["fetch_24h_total"], 100)
        self.assertEqual(result["error_rate_24h"], 0.3)  # (error 20 + rate_limited 10) / 100
        self.assertEqual(result["scope"], "all")
        # Coerces nested dicts into RankStatusCounts and ignores the extra keys.
        model = RankCollectionStats.model_validate(result)
        self.assertEqual(model.by_status.disabled, 10)
        self.assertEqual(model.fetch_24h.error, 20)
