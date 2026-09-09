from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))


tasks = importlib.import_module("src.services.overwatch_rank.tasks")
from shared.clients.circuit_breaker import CircuitBreakerOpen  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.schemas.settings import RankCollectionConfig  # noqa: E402
from src.domain.overwatch_rank import RankFetchResult  # noqa: E402
from src.services.overwatch_rank.client import OverFastRateLimited  # noqa: E402
from tests._fakes import session_factory as _session_factory  # noqa: E402


class FakeRedis:
    def __init__(self, keys: set[str] | None = None) -> None:
        self.store: dict[str, str] = dict.fromkeys(keys or set(), "1")
        self.counts: dict[str, int] = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        existed = key in self.store
        self.store.pop(key, None)
        return int(existed)

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        return True


class _FrozenClock:
    """Pins ``_reserve_slot``'s minute bucket so the window cannot roll mid-test."""

    fixed = datetime(2026, 1, 1, 12, 30, 15, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 - mirrors datetime.now's signature
        return cls.fixed


class EnqueueTests(IsolatedAsyncioTestCase):
    async def test_enqueue_is_deduped_per_battle_tag(self) -> None:
        from shared.schemas.events import FetchRankEvent

        redis = FakeRedis()
        event = FetchRankEvent(social_account_id=5, battle_tag="A#1", source="scheduled")
        with patch.object(tasks, "publish_message", AsyncMock()) as pub:
            first = await tasks.enqueue_fetch(event, broker=SimpleNamespace(), redis=redis)
            second = await tasks.enqueue_fetch(event, broker=SimpleNamespace(), redis=redis)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(pub.await_count, 1)


class ProcessFetchTests(IsolatedAsyncioTestCase):
    async def test_happy_path_records_result_and_clears_keys(self) -> None:
        redis = FakeRedis()
        session = SimpleNamespace(commit=AsyncMock())
        client = SimpleNamespace(
            fetch_summary=AsyncMock(return_value=RankFetchResult(status=enums.RankCollectionStatus.ok))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.mapping, "get_rank_mapping", AsyncMock(return_value=({}, "v1"))),
            patch.object(tasks.service, "record_result", AsyncMock(return_value=3)) as rec,
            patch.object(tasks.service, "log_fetch", AsyncMock()),
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 7, "battle_tag": "N#1"},
                redis=redis,
                client=client,
                session_factory=_session_factory(session),
            )
        rec.assert_awaited_once()
        self.assertNotIn(tasks._inflight_key(7), redis.store)
        self.assertNotIn(tasks._pending_key(7), redis.store)
        session.commit.assert_awaited()

    async def test_skips_when_already_in_flight(self) -> None:
        redis = FakeRedis({tasks._inflight_key(7)})
        client = SimpleNamespace(fetch_summary=AsyncMock())
        with patch.object(tasks.service, "record_result", AsyncMock()) as rec:
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 7, "battle_tag": "N#1"},
                redis=redis,
                client=client,
                session_factory=_session_factory(SimpleNamespace(commit=AsyncMock())),
            )
        rec.assert_not_awaited()
        client.fetch_summary.assert_not_awaited()

    async def test_over_the_per_minute_ceiling_defers_instead_of_fetching(self) -> None:
        """The per-minute ceiling must actually stop the fetch.

        It previously only slept for a fraction of a second and then issued the
        request anyway, so the ceiling bounded nothing — and on the priority
        queue (registration approvals, which bypass the scheduler's per-tick
        pacing) it is the only rate control there is.
        """
        redis = FakeRedis()
        client = SimpleNamespace(
            fetch_summary=AsyncMock(return_value=RankFetchResult(status=enums.RankCollectionStatus.ok))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig(rate_limit_per_minute=1)),
            ),
            patch.object(tasks.mapping, "get_rank_mapping", AsyncMock(return_value=({}, "v1"))),
            patch.object(tasks.service, "record_result", AsyncMock(return_value=1)),
            patch.object(tasks.service, "log_fetch", AsyncMock()),
            patch.object(tasks.service, "defer_tag", AsyncMock()) as defer,
            patch.object(tasks, "datetime", _FrozenClock),
        ):
            for social_account_id in (11, 12):
                await tasks.process_fetch_rank(
                    {
                        "event_type": "fetch_rank",
                        "social_account_id": social_account_id,
                        "battle_tag": f"N#{social_account_id}",
                    },
                    redis=redis,
                    client=client,
                    session_factory=_session_factory(SimpleNamespace(commit=AsyncMock())),
                )

        # First request consumes the window's single slot; the second is deferred
        # past the window instead of reaching OverFast.
        self.assertEqual(client.fetch_summary.await_count, 1)
        defer.assert_awaited_once()
        self.assertEqual(defer.await_args.kwargs["social_account_id"], 12)
        # Frozen at 12:30:15 → the window resets in 45s.
        self.assertEqual(defer.await_args.kwargs["delay_seconds"], 45)
        # The deferred tag's dedup keys are released so the scheduler can re-enqueue it.
        self.assertNotIn(tasks._inflight_key(12), redis.store)
        self.assertNotIn(tasks._pending_key(12), redis.store)

    async def test_rate_limited_sets_cooldown_and_records_failure(self) -> None:
        redis = FakeRedis()
        session = SimpleNamespace(commit=AsyncMock())
        client = SimpleNamespace(fetch_summary=AsyncMock(side_effect=OverFastRateLimited(retry_after=42)))
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.mapping, "get_rank_mapping", AsyncMock(return_value=({}, "v1"))),
            patch.object(tasks.service, "record_failure", AsyncMock()) as fail,
            patch.object(tasks.service, "log_fetch", AsyncMock()),
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 9, "battle_tag": "N#9"},
                redis=redis,
                client=client,
                session_factory=_session_factory(session),
            )
        self.assertEqual(redis.store.get(tasks.COOLDOWN_KEY), "1")
        fail.assert_awaited_once()

    async def test_open_circuit_is_handled_like_any_outage_instead_of_nacking(self) -> None:
        """An open breaker must not escape the handler.

        September 2026: OverFast's DNS record disappeared, the breaker opened, and
        ``CircuitBreakerOpen`` — unlike ``OverFastError`` — propagated out of the
        subscriber. FastStream nacked every message, so 21k dead fetches piled up
        in ``rank_fetch.dlq`` while the tags themselves were never marked failed.
        """
        redis = FakeRedis()
        session = SimpleNamespace(commit=AsyncMock())
        client = SimpleNamespace(
            fetch_summary=AsyncMock(side_effect=CircuitBreakerOpen("Circuit breaker for overfast is open"))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.mapping, "get_rank_mapping", AsyncMock(return_value=({}, "v1"))),
            patch.object(tasks.service, "record_failure", AsyncMock()) as fail,
            patch.object(tasks.service, "log_fetch", AsyncMock()) as log_fetch,
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 9, "battle_tag": "N#9"},
                redis=redis,
                client=client,
                session_factory=_session_factory(session),
            )

        # Recorded as a transient failure (backoff, never auto-disable) and written
        # to the fetch log, exactly like an OverFast 5xx.
        self.assertTrue(fail.await_args.kwargs["transient"])
        self.assertEqual(fail.await_args.kwargs["status"], enums.RankCollectionStatus.error)
        log_fetch.assert_awaited_once()
        # Dedup keys released, so the scheduler can retry the tag once OverFast is back.
        self.assertNotIn(tasks._inflight_key(9), redis.store)


class RegistrationHookTests(IsolatedAsyncioTestCase):
    async def test_enqueues_priority_for_each_user_tag(self) -> None:
        session = SimpleNamespace(commit=AsyncMock())
        data = {
            "event_type": "registration_approved",
            "tournament_id": 1,
            "workspace_id": 1,
            "registration_id": 2,
            "user_id": 50,
        }
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(
                tasks.service,
                "resolve_registration_targets",
                AsyncMock(return_value=[(10, "A#1"), (11, "B#2")]),
            ),
            patch.object(tasks.service, "ensure_state", AsyncMock()),
            patch.object(tasks, "enqueue_fetch", AsyncMock(return_value=True)) as enq,
        ):
            count = await tasks.handle_registration_approved(
                data, broker=SimpleNamespace(), redis=FakeRedis(), session_factory=_session_factory(session)
            )
        self.assertEqual(count, 2)
        self.assertEqual(enq.await_count, 2)
        self.assertTrue(all(c.kwargs["priority"] for c in enq.await_args_list))

    async def test_skips_unlinked_registration(self) -> None:
        data = {
            "event_type": "registration_approved",
            "tournament_id": 1,
            "workspace_id": 1,
            "registration_id": 2,
            "user_id": None,
        }
        with patch.object(tasks, "enqueue_fetch", AsyncMock()) as enq:
            count = await tasks.handle_registration_approved(data, broker=SimpleNamespace())
        self.assertEqual(count, 0)
        enq.assert_not_awaited()
