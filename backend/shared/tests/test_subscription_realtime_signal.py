"""When the resolver tells a workspace its entitlements moved — and when it stays quiet.

Both halves are load-bearing:

- **Quiet on an unchanged re-check.** The collector sweeps with ``force_refresh=True``
  on every tick, so wiring the signal to *attempts* (as the check log correctly is)
  would make every open admin page refetch forever. Only a verdict that actually
  moved is news.
- **One signal per pass, not per patron.** A sweep that flips 40 verdicts must cost
  each subscriber one refetch. This is asserted with a count, not a truthiness
  check, because a per-user emit passes any "did it fire?" test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from shared.core.enums import SubscriptionCollectionSource
from shared.services.subscriptions import SubscriptionState, SubscriptionVerdict
from shared.services.subscriptions.entitlements import (
    SUBSCRIPTION_TTL_SECONDS,
    ProviderConfigRow,
    StoredEntitlement,
    SubscriptionResolver,
)

WS = 7
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _verdict(state: str, *, tier: int | None = None, source: str = "discord_role") -> SubscriptionVerdict:
    return SubscriptionVerdict(
        state=state,
        tier_rank=tier,
        tier_label=f"Tier {tier}" if tier else None,
        source=source,
        checked_at=NOW,
        expires_at=NOW + timedelta(seconds=SUBSCRIPTION_TTL_SECONDS),
        evidence={},
    )


def _stored(state: str, *, tier: int | None = None, source: str = "discord_role") -> StoredEntitlement:
    return StoredEntitlement(
        state=state,
        tier_rank=tier,
        tier_label=f"Tier {tier}" if tier else None,
        source=source,
        # Deliberately in the past and expired: every user must land in `stale` so
        # the live path runs and the ONLY thing deciding the signal is the verdict.
        checked_at=NOW - timedelta(hours=1),
        expires_at=NOW - timedelta(minutes=1),
    )


class _Store:
    def __init__(self, *, configs=None, stored=None) -> None:
        self._configs = configs or {}
        self._stored = stored or {}
        self.upserts: list[tuple] = []
        self.upsert_many_calls = 0

    async def load_configs(self, workspace_id, providers):
        return {p: self._configs[p] for p in providers if p in self._configs}

    async def load_entitlements(self, workspace_id, auth_user_ids, providers):
        return {
            key: row for key, row in self._stored.items() if key[0] in set(auth_user_ids) and key[1] in set(providers)
        }

    async def upsert(self, workspace_id, auth_user_id, provider, verdict):
        self.upserts.append((workspace_id, auth_user_id, provider, verdict))

    async def upsert_many(self, workspace_id, provider, verdicts):
        self.upsert_many_calls += 1
        for auth_user_id, verdict in verdicts.items():
            self.upserts.append((workspace_id, auth_user_id, provider, verdict))


class _EventSink:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._error = error

    async def subscriptions_updated(self, **kwargs):
        if self._error is not None:
            raise self._error
        self.calls.append(kwargs)


class _Strategy:
    def __init__(self, verdicts=None) -> None:
        self._verdicts = verdicts or {}

    async def resolve_many(self, *, config, auth_user_ids):
        return {uid: v for uid, v in self._verdicts.items() if uid in set(auth_user_ids)}


def _enabled(config: dict | None = None) -> ProviderConfigRow:
    return ProviderConfigRow(provider="boosty", enabled=True, config=config or {"guild_id": "9"})


def _resolver(store, strategies, events=None) -> SubscriptionResolver:
    return SubscriptionResolver(store=store, strategies=strategies, now=lambda: NOW, event_sink=events)


class TestChangeIsSignalled(IsolatedAsyncioTestCase):
    async def test_a_first_verdict_is_signalled(self):
        store = _Store(configs={"boosty": _enabled()})
        events = _EventSink()

        await _resolver(store, {"boosty": _Strategy({1: _verdict(SubscriptionState.ACTIVE, tier=2)})}, events).resolve(
            workspace_id=WS,
            auth_user_ids=[1],
            providers=["boosty"],
            source=SubscriptionCollectionSource.registration,
        )

        assert events.calls == [{"workspace_id": WS, "trigger": SubscriptionCollectionSource.registration}]

    async def test_a_revoked_subscription_is_signalled(self):
        store = _Store(
            configs={"boosty": _enabled()},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2)},
        )
        events = _EventSink()

        await _resolver(store, {"boosty": _Strategy({1: _verdict(SubscriptionState.INACTIVE)})}, events).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"], force_refresh=True
        )

        assert len(events.calls) == 1

    async def test_a_tier_upgrade_is_signalled(self):
        """Same state, different level — a rank change is exactly what a roster reads."""
        store = _Store(
            configs={"boosty": _enabled()},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=1)},
        )
        events = _EventSink()

        await _resolver(store, {"boosty": _Strategy({1: _verdict(SubscriptionState.ACTIVE, tier=2)})}, events).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"], force_refresh=True
        )

        assert len(events.calls) == 1

    async def test_a_whole_sweep_costs_one_signal_and_one_write(self):
        """Forty flipped verdicts, one refetch per subscriber -- and, now, one write."""
        store = _Store(
            configs={"boosty": _enabled()},
            stored={(uid, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2) for uid in range(1, 41)},
        )
        strategy = _Strategy({uid: _verdict(SubscriptionState.INACTIVE) for uid in range(1, 41)})
        events = _EventSink()

        await _resolver(store, {"boosty": strategy}, events).resolve(
            workspace_id=WS, auth_user_ids=list(range(1, 41)), providers=["boosty"], force_refresh=True
        )

        assert len(store.upserts) == 40
        assert store.upsert_many_calls == 1, "40 stale users must cost one round trip, not 40"
        assert len(events.calls) == 1


class TestNoChangeIsSilent(IsolatedAsyncioTestCase):
    async def test_a_forced_recheck_that_confirms_the_same_verdict_is_silent(self):
        """THE regression guard: the collector forces a refresh on every tick, so a
        signal per attempt would refetch every open page forever."""
        store = _Store(
            configs={"boosty": _enabled()},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2)},
        )
        events = _EventSink()

        await _resolver(store, {"boosty": _Strategy({1: _verdict(SubscriptionState.ACTIVE, tier=2)})}, events).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"], force_refresh=True
        )

        # The row was rewritten (checked_at moved), and that is precisely NOT news.
        assert len(store.upserts) == 1
        assert events.calls == []

    async def test_a_cache_hit_is_silent(self):
        store = _Store(
            configs={"boosty": _enabled()},
            stored={
                (1, "boosty"): StoredEntitlement(
                    state=SubscriptionState.ACTIVE,
                    tier_rank=2,
                    tier_label="Tier 2",
                    source="discord_role",
                    checked_at=NOW - timedelta(seconds=10),
                    expires_at=None,
                )
            },
        )
        events = _EventSink()

        await _resolver(store, {"boosty": _Strategy()}, events).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )

        assert events.calls == []

    async def test_an_unresolved_user_is_silent(self):
        """The strategy declined to answer, so nothing was persisted to announce."""
        store = _Store(configs={"boosty": _enabled()})
        events = _EventSink()

        await _resolver(store, {"boosty": _Strategy()}, events).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )

        assert store.upserts == []
        assert events.calls == []


class TestSinkIsOptionalAndNonFatal(IsolatedAsyncioTestCase):
    async def test_no_sink_still_resolves(self):
        store = _Store(configs={"boosty": _enabled()})

        out = await _resolver(store, {"boosty": _Strategy({1: _verdict(SubscriptionState.ACTIVE, tier=2)})}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )

        assert out[1]["boosty"].state == SubscriptionState.ACTIVE

    async def test_a_broken_sink_never_breaks_the_verdict(self):
        """A missed invalidation self-heals on reconnect; a refused admission does not."""
        store = _Store(configs={"boosty": _enabled()})
        events = _EventSink(error=RuntimeError("redis gone"))

        out = await _resolver(
            store, {"boosty": _Strategy({1: _verdict(SubscriptionState.ACTIVE, tier=2)})}, events
        ).resolve(workspace_id=WS, auth_user_ids=[1], providers=["boosty"])

        assert out[1]["boosty"].state == SubscriptionState.ACTIVE
        assert len(store.upserts) == 1
