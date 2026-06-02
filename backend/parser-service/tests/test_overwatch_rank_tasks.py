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

tasks = importlib.import_module("src.services.overwatch_rank.tasks")
from shared.core import enums  # noqa: E402
from shared.schemas.settings import RankCollectionConfig  # noqa: E402

from src.services.overwatch_rank.client import OverFastRateLimited  # noqa: E402
from src.services.overwatch_rank.schemas import RankFetchResult  # noqa: E402


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


def _session_factory(session):
    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    return lambda: Ctx()


class EnqueueTests(IsolatedAsyncioTestCase):
    async def test_enqueue_is_deduped_per_battle_tag(self) -> None:
        from shared.schemas.events import FetchRankEvent

        redis = FakeRedis()
        event = FetchRankEvent(battle_tag_id=5, battle_tag="A#1", source="scheduled")
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
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "battle_tag_id": 7, "battle_tag": "N#1"},
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
                {"event_type": "fetch_rank", "battle_tag_id": 7, "battle_tag": "N#1"},
                redis=redis,
                client=client,
                session_factory=_session_factory(SimpleNamespace(commit=AsyncMock())),
            )
        rec.assert_not_awaited()
        client.fetch_summary.assert_not_awaited()

    async def test_rate_limited_sets_cooldown_and_records_failure(self) -> None:
        redis = FakeRedis()
        session = SimpleNamespace(commit=AsyncMock())
        client = SimpleNamespace(
            fetch_summary=AsyncMock(side_effect=OverFastRateLimited(retry_after=42))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.mapping, "get_rank_mapping", AsyncMock(return_value=({}, "v1"))),
            patch.object(tasks.service, "record_failure", AsyncMock()) as fail,
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "battle_tag_id": 9, "battle_tag": "N#9"},
                redis=redis,
                client=client,
                session_factory=_session_factory(session),
            )
        self.assertEqual(redis.store.get(tasks.COOLDOWN_KEY), "1")
        fail.assert_awaited_once()


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
                tasks.service,
                "promote_user_tags",
                AsyncMock(return_value=[(10, "A#1"), (11, "B#2")]),
            ),
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
