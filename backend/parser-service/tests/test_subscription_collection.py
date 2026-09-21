from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

from shared.core.enums import SubscriptionCollectionSource  # noqa: E402
from shared.schemas.settings import SubscriptionCollectionConfig  # noqa: E402
from shared.services.settings_provider import settings_provider  # noqa: E402

BOOSTY_ONLY = {"mode": "all", "requirements": [{"provider": "boosty", "min_tier_rank": 2}]}
BOTH = {
    "mode": "any",
    "requirements": [{"provider": "boosty", "min_tier_rank": 1}, {"provider": "twitch", "min_tier_rank": 1}],
}


def _rows(*rows):
    """A session whose single ``execute`` returns ``rows``."""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = list(rows)
    session.execute = AsyncMock(return_value=result)
    return session


class FindTournamentsTests(IsolatedAsyncioTestCase):
    async def test_returns_targets_with_providers_from_the_requirement(self):
        from src.services.subscription_collection import service

        res = await service.find_tournaments_requiring_subscriptions(_rows((10, 1, BOOSTY_ONLY), (20, 2, BOTH)))

        self.assertEqual([(t.tournament_id, t.workspace_id) for t in res], [(10, 1), (20, 2)])
        # Providers come from each form's own rule, not a hardcoded list: resolving
        # a provider the tournament does not require would write entitlements
        # nobody reads and bury the history in `provider_not_configured` noise.
        self.assertEqual(res[0].providers, ("boosty",))
        self.assertEqual(sorted(res[1].providers), ["boosty", "twitch"])

    async def test_skips_empty_requirement(self):
        from src.services.subscription_collection import service

        # `require_subscription` is a master toggle kept separate from the rule
        # blob, so it can legitimately be on while the blob is still empty.
        res = await service.find_tournaments_requiring_subscriptions(_rows((10, 1, {}), (20, 2, BOTH)))
        self.assertEqual([t.tournament_id for t in res], [20])

    async def test_skips_malformed_requirement_instead_of_raising(self):
        from src.services.subscription_collection import service

        res = await service.find_tournaments_requiring_subscriptions(
            _rows((10, 1, {"mode": "nonsense", "requirements": [{"provider": "boosty"}]}), (20, 2, BOTH))
        )
        self.assertEqual([t.tournament_id for t in res], [20])


class LoadParticipantsTests(IsolatedAsyncioTestCase):
    async def test_load_auth_user_ids_for_tournament(self):
        from src.services.subscription_collection import service

        res = await service.load_auth_user_ids_for_tournament(_rows((100,), (200,)), 10)
        self.assertEqual(res, [100, 200])


class CollectTests(IsolatedAsyncioTestCase):
    def _target(self, providers=("boosty", "twitch")):
        from src.services.subscription_collection.service import TournamentTarget

        return TournamentTarget(tournament_id=10, workspace_id=1, providers=tuple(providers))

    async def test_no_targets_is_a_noop(self):
        from src.services.subscription_collection import service

        session = AsyncMock()
        with patch.object(service, "find_tournaments_requiring_subscriptions", AsyncMock(return_value=[])):
            self.assertEqual(await service.collect_subscriptions_for_active_tournaments(session), 0)

    async def test_resolves_the_targets_providers_and_commits(self):
        from src.services.subscription_collection import service

        session = AsyncMock()
        resolver = AsyncMock()
        resolver.resolve.return_value = {100: {}, 200: {}}

        with (
            patch.object(service, "find_tournaments_requiring_subscriptions", AsyncMock(return_value=[self._target()])),
            patch.object(service, "load_auth_user_ids_for_tournament", AsyncMock(return_value=[100, 200])),
            patch.object(service, "build_resolver", return_value=resolver),
        ):
            res = await service.collect_subscriptions_for_active_tournaments(session)

        self.assertEqual(res, 2)
        resolver.resolve.assert_called_once_with(
            workspace_id=1,
            auth_user_ids=[100, 200],
            providers=["boosty", "twitch"],
            force_refresh=True,
            source=SubscriptionCollectionSource.scheduled,
        )
        # Without a commit nothing survives the session — neither the entitlement
        # upserts nor the history rows. This is the regression that made the
        # collector a no-op.
        session.commit.assert_awaited_once()

    async def test_batches_participants_and_commits_each_batch(self):
        from src.services.subscription_collection import service

        session = AsyncMock()
        resolver = AsyncMock()
        resolver.resolve.return_value = {1: {}}

        with (
            patch.object(service, "find_tournaments_requiring_subscriptions", AsyncMock(return_value=[self._target()])),
            patch.object(service, "load_auth_user_ids_for_tournament", AsyncMock(return_value=[1, 2, 3, 4, 5])),
            patch.object(service, "build_resolver", return_value=resolver),
        ):
            await service.collect_subscriptions_for_active_tournaments(session, batch_size=2)

        self.assertEqual(
            [call.kwargs["auth_user_ids"] for call in resolver.resolve.await_args_list], [[1, 2], [3, 4], [5]]
        )
        self.assertEqual(session.commit.await_count, 3)

    async def test_provider_failure_rolls_back_and_keeps_sweeping(self):
        from src.services.subscription_collection import service

        session = AsyncMock()
        resolver = AsyncMock()
        resolver.resolve.side_effect = RuntimeError("discord down")
        other = service.TournamentTarget(tournament_id=20, workspace_id=2, providers=("twitch",))

        with (
            patch.object(
                service,
                "find_tournaments_requiring_subscriptions",
                AsyncMock(return_value=[self._target(), other]),
            ),
            patch.object(service, "load_auth_user_ids_for_tournament", AsyncMock(return_value=[100])),
            patch.object(service, "build_resolver", return_value=resolver),
        ):
            res = await service.collect_subscriptions_for_active_tournaments(session)

        self.assertEqual(res, 0)
        # One tournament's outage must not abort the sweep, and the rollback is
        # what lets the next target reuse the session.
        self.assertEqual(resolver.resolve.await_count, 2)
        self.assertEqual(session.rollback.await_count, 2)


class SchedulerTests(IsolatedAsyncioTestCase):
    def _session_factory(self, session):
        cm = AsyncMock()
        cm.__aenter__.return_value = session
        return MagicMock(return_value=cm)

    async def test_runs_when_no_scheduled_check_was_ever_recorded(self):
        from shared.services.distributed_lock import DistributedLockToken
        from src.services.subscription_collection import scheduler

        session = AsyncMock()
        session.scalar = AsyncMock(return_value=None)
        token = DistributedLockToken(key=scheduler.LEADER_LOCK_KEY, value="token-123")
        release = AsyncMock()
        redis = AsyncMock()

        with (
            patch(
                "src.services.subscription_collection.scheduler.acquire_distributed_lock",
                AsyncMock(return_value=token),
            ),
            patch("src.services.subscription_collection.scheduler.release_distributed_lock", release),
            patch.object(
                settings_provider,
                "get_subscription_collection_config",
                AsyncMock(return_value=SubscriptionCollectionConfig(enabled=True)),
            ),
            patch.object(
                scheduler.subscription_collection_service,
                "collect_subscriptions_for_active_tournaments",
                AsyncMock(return_value=5),
            ),
        ):
            count = await scheduler.run_subscription_collection_tick(self._session_factory(session), redis)

        self.assertEqual(count, 5)
        release.assert_awaited_once_with(redis, token)

    async def test_skips_when_the_interval_has_not_elapsed(self):
        from shared.services.distributed_lock import DistributedLockToken
        from src.services.subscription_collection import scheduler

        cfg = SubscriptionCollectionConfig(enabled=True, interval_seconds=1800)
        session = AsyncMock()
        # Last scheduled check was 5 minutes ago; the tick fires every 60s but must
        # honour the admin-configured 30-minute interval the dashboard echoes.
        session.scalar = AsyncMock(return_value=datetime.now(UTC) - timedelta(minutes=5))
        token = DistributedLockToken(key=scheduler.LEADER_LOCK_KEY, value="t")
        release = AsyncMock()
        collect = AsyncMock(return_value=5)

        with (
            patch(
                "src.services.subscription_collection.scheduler.acquire_distributed_lock",
                AsyncMock(return_value=token),
            ),
            patch("src.services.subscription_collection.scheduler.release_distributed_lock", release),
            patch.object(
                settings_provider,
                "get_subscription_collection_config",
                AsyncMock(return_value=cfg),
            ),
            patch.object(
                scheduler.subscription_collection_service, "collect_subscriptions_for_active_tournaments", collect
            ),
        ):
            count = await scheduler.run_subscription_collection_tick(self._session_factory(session), AsyncMock())

        self.assertEqual(count, 0)
        collect.assert_not_awaited()
        release.assert_awaited_once()

    async def test_runs_once_the_interval_elapsed(self):
        from shared.services.distributed_lock import DistributedLockToken
        from src.services.subscription_collection import scheduler

        cfg = SubscriptionCollectionConfig(enabled=True, interval_seconds=1800)
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=datetime.now(UTC) - timedelta(minutes=31))
        token = DistributedLockToken(key=scheduler.LEADER_LOCK_KEY, value="t")
        collect = AsyncMock(return_value=7)

        with (
            patch(
                "src.services.subscription_collection.scheduler.acquire_distributed_lock",
                AsyncMock(return_value=token),
            ),
            patch("src.services.subscription_collection.scheduler.release_distributed_lock", AsyncMock()),
            patch.object(
                settings_provider,
                "get_subscription_collection_config",
                AsyncMock(return_value=cfg),
            ),
            patch.object(
                scheduler.subscription_collection_service, "collect_subscriptions_for_active_tournaments", collect
            ),
        ):
            count = await scheduler.run_subscription_collection_tick(self._session_factory(session), AsyncMock())

        self.assertEqual(count, 7)
        self.assertEqual(collect.await_args.kwargs["batch_size"], cfg.batch_size)

    async def test_disabled_config_skips_before_reading_the_log(self):
        from shared.services.distributed_lock import DistributedLockToken
        from src.services.subscription_collection import scheduler

        session = AsyncMock()
        token = DistributedLockToken(key=scheduler.LEADER_LOCK_KEY, value="t")
        collect = AsyncMock()

        with (
            patch(
                "src.services.subscription_collection.scheduler.acquire_distributed_lock",
                AsyncMock(return_value=token),
            ),
            patch("src.services.subscription_collection.scheduler.release_distributed_lock", AsyncMock()),
            patch.object(
                settings_provider,
                "get_subscription_collection_config",
                AsyncMock(return_value=SubscriptionCollectionConfig(enabled=False)),
            ),
            patch.object(
                scheduler.subscription_collection_service, "collect_subscriptions_for_active_tournaments", collect
            ),
        ):
            count = await scheduler.run_subscription_collection_tick(self._session_factory(session), AsyncMock())

        self.assertEqual(count, 0)
        collect.assert_not_awaited()
        session.scalar.assert_not_awaited()

    async def test_lock_unavailable_skips_without_releasing(self):
        from shared.services.distributed_lock import DistributedLockUnavailable
        from src.services.subscription_collection import scheduler

        release = AsyncMock()
        with (
            patch(
                "src.services.subscription_collection.scheduler.acquire_distributed_lock",
                AsyncMock(side_effect=DistributedLockUnavailable("locked")),
            ),
            patch("src.services.subscription_collection.scheduler.release_distributed_lock", release),
        ):
            count = await scheduler.run_subscription_collection_tick(AsyncMock(), AsyncMock())

        self.assertEqual(count, 0)
        release.assert_not_called()
