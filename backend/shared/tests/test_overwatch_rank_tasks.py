from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.clients.circuit_breaker import CircuitBreakerOpen
from shared.core import enums
from shared.disciplines.overwatch.collector import tasks
from shared.disciplines.overwatch.collector.client import OverFastRateLimited
from shared.disciplines.overwatch.collector.domain import ParsedProfile, RankFetchResult
from shared.schemas.settings import RankCollectionConfig


def _session_factory(session):
    """A zero-arg callable producing a minimal async-context-manager session stand-in."""

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _Ctx()


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
    """Pins ``reserve_slot``'s minute bucket so the window cannot roll mid-test."""

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
            fetch_profile=AsyncMock(return_value=RankFetchResult(status=enums.RankCollectionStatus.ok))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
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
        client = SimpleNamespace(fetch_profile=AsyncMock())
        with patch.object(tasks.service, "record_result", AsyncMock()) as rec:
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 7, "battle_tag": "N#1"},
                redis=redis,
                client=client,
                session_factory=_session_factory(SimpleNamespace(commit=AsyncMock())),
            )
        rec.assert_not_awaited()
        client.fetch_profile.assert_not_awaited()

    async def test_over_the_per_minute_ceiling_defers_instead_of_fetching(self) -> None:
        """The per-minute ceiling must actually stop the fetch.

        It previously only slept for a fraction of a second and then issued the
        request anyway, so the ceiling bounded nothing — and on the priority
        queue (registration approvals, which bypass the scheduler's per-tick
        pacing) it is the only rate control there is.
        """
        redis = FakeRedis()
        client = SimpleNamespace(
            fetch_profile=AsyncMock(return_value=RankFetchResult(status=enums.RankCollectionStatus.ok))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig(rate_limit_per_minute=1)),
            ),
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
        self.assertEqual(client.fetch_profile.await_count, 1)
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
        client = SimpleNamespace(fetch_profile=AsyncMock(side_effect=OverFastRateLimited(retry_after=42)))
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
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
            fetch_profile=AsyncMock(side_effect=CircuitBreakerOpen("Circuit breaker for overfast is open"))
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
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

    async def test_a_tag_that_stopped_resolving_is_read_by_its_blizzard_id(self) -> None:
        """A renamed account keeps being collected: the not-found tag falls back to the stored Blizzard id."""
        renamed = RankFetchResult(status=enums.RankCollectionStatus.ok, profile=_PROFILE)
        client = SimpleNamespace(
            fetch_profile=AsyncMock(
                side_effect=[RankFetchResult(status=enums.RankCollectionStatus.not_found), renamed]
            ),
            search_players=AsyncMock(return_value=[]),
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.career, "canonical_id", AsyncMock(return_value="aa|bb")),
            patch.object(tasks.career, "record", AsyncMock(return_value=(0, False))) as record,
            patch.object(tasks.service, "record_result", AsyncMock(return_value=0)) as rec,
            patch.object(tasks.service, "log_fetch", AsyncMock()),
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 7, "battle_tag": "N#1"},
                redis=FakeRedis(),
                client=client,
                session_factory=_session_factory(SimpleNamespace(commit=AsyncMock())),
            )
        self.assertEqual([call.args[0] for call in client.fetch_profile.await_args_list], ["N#1", "aa|bb"])
        self.assertIs(rec.await_args.kwargs["result"], renamed)
        record.assert_awaited_once()

    async def test_a_failing_career_write_costs_the_poll_nothing(self) -> None:
        """Ranks are committed first; a career failure is logged, the fetch log is written, the keys are released."""
        redis = FakeRedis()
        session = SimpleNamespace(commit=AsyncMock())
        client = SimpleNamespace(
            fetch_profile=AsyncMock(
                return_value=RankFetchResult(status=enums.RankCollectionStatus.ok, profile=_PROFILE)
            )
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.career, "record", AsyncMock(side_effect=RuntimeError("bad jsonb"))),
            patch.object(tasks.service, "record_result", AsyncMock(return_value=2)) as rec,
            patch.object(tasks.service, "record_failure", AsyncMock()) as fail,
            patch.object(tasks.service, "log_fetch", AsyncMock()) as log_fetch,
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 7, "battle_tag": "N#1"},
                redis=redis,
                client=client,
                session_factory=_session_factory(session),
            )
        rec.assert_awaited_once()
        fail.assert_not_awaited()
        self.assertEqual(log_fetch.await_args.kwargs["status"], "ok")
        self.assertNotIn(tasks._inflight_key(7), redis.store)

    async def test_a_rate_limited_search_cools_overfast_down_but_never_fails_the_account(self) -> None:
        redis = FakeRedis()
        client = SimpleNamespace(
            fetch_profile=AsyncMock(
                return_value=RankFetchResult(status=enums.RankCollectionStatus.ok, profile=_PROFILE)
            ),
            search_players=AsyncMock(side_effect=OverFastRateLimited(retry_after=30)),
        )
        with (
            patch.object(
                tasks.settings_provider,
                "get_rank_collection_config",
                AsyncMock(return_value=RankCollectionConfig()),
            ),
            patch.object(tasks.career, "record", AsyncMock(return_value=(1, True))),
            patch.object(tasks.career, "set_canonical_id", AsyncMock()) as stamp,
            patch.object(tasks.service, "record_result", AsyncMock(return_value=0)),
            patch.object(tasks.service, "record_failure", AsyncMock()) as fail,
            patch.object(tasks.service, "log_fetch", AsyncMock()),
        ):
            await tasks.process_fetch_rank(
                {"event_type": "fetch_rank", "social_account_id": 7, "battle_tag": "N#1"},
                redis=redis,
                client=client,
                session_factory=_session_factory(SimpleNamespace(commit=AsyncMock())),
            )
        fail.assert_not_awaited()
        # No attempt stamped: the search is retried on the next poll instead of a week later.
        stamp.assert_not_awaited()
        self.assertEqual(redis.store.get(tasks.COOLDOWN_KEY), "1")


_PROFILE = ParsedProfile(display_name="N", avatar_url=None, attrs={}, upstream_updated_at=None)


def _refresh(**values: Any) -> dict[str, Any]:
    return {
        "user_id": 50,
        "discipline": "overwatch",
        "workspace_id": 1,
        "source": "tournament_registration",
        "registration_id": 2,
        **values,
    }


class PlayerRefreshTests(IsolatedAsyncioTestCase):
    async def test_generic_identity_is_converted_to_a_battletag_only_at_the_ow_boundary(self) -> None:
        for identity, expected in [
            ({"provider": "battlenet", "handle": "Battle#1234"}, "Battle#1234"),
            ({"provider": "riot", "handle": "Riot Name#EUW"}, None),
            (None, None),
        ]:
            session = SimpleNamespace(commit=AsyncMock())
            with (
                patch.object(
                    tasks.settings_provider,
                    "get_rank_collection_config",
                    AsyncMock(return_value=RankCollectionConfig()),
                ),
                patch.object(tasks.service, "resolve_registration_targets", AsyncMock(return_value=[])) as targets,
            ):
                count = await tasks.handle_player_refresh(
                    _refresh(identity=identity), session_factory=_session_factory(session)
                )
            self.assertEqual(count, 0)
            self.assertEqual(targets.await_args.kwargs["fallback_battle_tag"], expected)

    async def test_enqueues_priority_for_each_user_tag(self) -> None:
        session = SimpleNamespace(commit=AsyncMock())
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
            count = await tasks.handle_player_refresh(
                _refresh(), broker=SimpleNamespace(), redis=FakeRedis(), session_factory=_session_factory(session)
            )
        self.assertEqual(count, 2)
        self.assertEqual(enq.await_count, 2)
        self.assertTrue(all(c.kwargs["priority"] for c in enq.await_args_list))

    async def test_skips_another_games_refresh(self) -> None:
        with patch.object(tasks, "enqueue_fetch", AsyncMock()) as enq:
            count = await tasks.handle_player_refresh(
                _refresh(discipline="lol", source="mix_signup", registration_id=None), broker=SimpleNamespace()
            )
        self.assertEqual(count, 0)
        enq.assert_not_awaited()
