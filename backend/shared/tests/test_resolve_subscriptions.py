"""Resolver tests: caching, batching and requirement composition.

No database. The data-access boundary (``EntitlementStore``) and the per-provider
strategies are injected, matching the repo's convention of faking the boundary
rather than the SQLAlchemy session (see shared/tests/test_rpc_crud.py).

Runs under stdlib unittest -- there is no pytest-asyncio here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import IsolatedAsyncioTestCase

from shared.services.subscriptions import (
    Outcome,
    SubscriptionSource,
    SubscriptionState,
    SubscriptionVerdict,
    parse_requirement,
)
from shared.services.subscriptions.entitlements import (
    SUBSCRIPTION_TTL_SECONDS,
    ProviderConfigRow,
    StoredEntitlement,
    SubscriptionResolver,
)

WS = 7
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _verdict(state: str, tier: int | None = None, source: str = "test") -> SubscriptionVerdict:
    return SubscriptionVerdict(
        state=state,
        tier_rank=tier,
        tier_label=None,
        source=source,
        checked_at=NOW,
        expires_at=NOW + timedelta(seconds=SUBSCRIPTION_TTL_SECONDS),
        evidence={},
    )


def _stored(
    state: str,
    *,
    tier: int | None = None,
    age_seconds: int = 0,
    expires_in: int | None = None,
    source: str = SubscriptionSource.DISCORD_ROLE,
) -> StoredEntitlement:
    return StoredEntitlement(
        state=state,
        tier_rank=tier,
        tier_label=None,
        source=source,
        checked_at=NOW - timedelta(seconds=age_seconds),
        expires_at=None if expires_in is None else NOW + timedelta(seconds=expires_in),
        evidence={},
    )


class _FakeStore:
    """Records how it was called so batching can be asserted."""

    def __init__(
        self,
        *,
        configs: dict[str, ProviderConfigRow] | None = None,
        stored: dict[tuple[int, str], StoredEntitlement] | None = None,
    ) -> None:
        self._configs = configs or {}
        self._stored = stored or {}
        self.config_calls: list[tuple[int, tuple[str, ...]]] = []
        self.load_calls: list[tuple[int, tuple[int, ...], tuple[str, ...]]] = []
        self.upserts: list[tuple[int, int, str, SubscriptionVerdict]] = []
        self.upsert_many_calls: list[tuple[int, str, int]] = []  # (workspace_id, provider, count)

    async def load_configs(self, workspace_id, providers):
        self.config_calls.append((workspace_id, tuple(providers)))
        return {p: self._configs[p] for p in providers if p in self._configs}

    async def load_entitlements(self, workspace_id, auth_user_ids, providers):
        self.load_calls.append((workspace_id, tuple(auth_user_ids), tuple(providers)))
        return {
            key: row for key, row in self._stored.items() if key[0] in set(auth_user_ids) and key[1] in set(providers)
        }

    async def upsert(self, workspace_id, auth_user_id, provider, verdict):
        self.upserts.append((workspace_id, auth_user_id, provider, verdict))

    async def upsert_many(self, workspace_id, provider, verdicts):
        self.upsert_many_calls.append((workspace_id, provider, len(verdicts)))
        for auth_user_id, verdict in verdicts.items():
            self.upserts.append((workspace_id, auth_user_id, provider, verdict))


class _FakeStrategy:
    """One provider's live resolution, with a call log and optional explosion."""

    def __init__(self, verdicts=None, *, error: Exception | None = None, default=None) -> None:
        self._verdicts = verdicts or {}
        self._error = error
        self._default = default
        self.calls: list[tuple[dict[str, Any], tuple[int, ...]]] = []

    async def resolve_many(self, *, config, auth_user_ids):
        self.calls.append((config, tuple(auth_user_ids)))
        if self._error is not None:
            raise self._error
        out = {}
        for uid in auth_user_ids:
            verdict = self._verdicts.get(uid, self._default)
            if verdict is not None:
                out[uid] = verdict
        return out


def _enabled(provider: str, config: dict | None = None) -> ProviderConfigRow:
    return ProviderConfigRow(provider=provider, enabled=True, config=config or {"guild_id": "9"})


def _resolver(store, strategies, *, now=NOW) -> SubscriptionResolver:
    return SubscriptionResolver(store=store, strategies=strategies, now=lambda: now)


class TestEmptyInputs(IsolatedAsyncioTestCase):
    async def test_no_users_touches_nothing(self):
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        result = await _resolver(store, {}).resolve(workspace_id=WS, auth_user_ids=[], providers=["boosty"])
        assert result == {}
        assert store.config_calls == []
        assert store.load_calls == []

    async def test_no_providers_touches_nothing(self):
        store = _FakeStore()
        result = await _resolver(store, {}).resolve(workspace_id=WS, auth_user_ids=[1], providers=[])
        assert result == {}
        assert store.load_calls == []


class TestUnconfiguredProvider(IsolatedAsyncioTestCase):
    async def test_missing_config_yields_unknown_and_calls_no_strategy(self):
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 2))
        store = _FakeStore()
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].state == SubscriptionState.UNKNOWN
        assert result[1]["boosty"].evidence["reason"] == "provider_not_configured"
        assert strategy.calls == []

    async def test_disabled_config_yields_unknown(self):
        store = _FakeStore(configs={"boosty": ProviderConfigRow(provider="boosty", enabled=False, config={})})
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 2))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].state == SubscriptionState.UNKNOWN
        assert result[1]["boosty"].evidence["reason"] == "provider_disabled"
        assert strategy.calls == []

    async def test_one_broken_provider_does_not_blank_the_others(self):
        store = _FakeStore(configs={"twitch": _enabled("twitch", {"broadcaster_id": "1"})})
        twitch = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        result = await _resolver(store, {"twitch": twitch}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty", "twitch"]
        )
        assert result[1]["boosty"].state == SubscriptionState.UNKNOWN
        assert result[1]["twitch"].state == SubscriptionState.ACTIVE

    async def test_no_registered_strategy_is_unknown_not_a_crash(self):
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        result = await _resolver(store, {}).resolve(workspace_id=WS, auth_user_ids=[1], providers=["boosty"])
        assert result[1]["boosty"].state == SubscriptionState.UNKNOWN
        assert result[1]["boosty"].evidence["reason"] == "no_strategy_for_provider"


class TestCaching(IsolatedAsyncioTestCase):
    async def test_fresh_row_is_reused_without_calling_the_provider(self):
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2, age_seconds=60)},
        )
        strategy = _FakeStrategy(error=AssertionError("must not be called"))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].tier_rank == 2
        assert strategy.calls == []
        assert store.upserts == []

    async def test_stale_row_is_refreshed_and_upserted(self):
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.INACTIVE, age_seconds=SUBSCRIPTION_TTL_SECONDS + 1)},
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 3))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].tier_rank == 3
        assert strategy.calls[0][1] == (1,)
        assert [u[1] for u in store.upserts] == [1]

    async def test_missing_row_is_resolved_live(self):
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].state == SubscriptionState.ACTIVE
        assert store.upserts

    async def test_expired_row_is_refreshed_even_when_recently_checked(self):
        """`expires_at` in the past wins over a young `checked_at`."""
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2, age_seconds=1, expires_in=-1)},
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].state == SubscriptionState.INACTIVE

    async def test_force_refresh_ignores_a_fresh_row(self):
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2, age_seconds=1)},
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"], force_refresh=True
        )
        assert result[1]["boosty"].state == SubscriptionState.INACTIVE
        assert strategy.calls

    async def test_allow_stale_reuses_an_old_row_and_never_calls_the_provider(self):
        """The display read: a TTL-expired row is still the answer, a user with no
        row is `unknown`, and nothing is fetched, persisted or logged."""
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2, age_seconds=SUBSCRIPTION_TTL_SECONDS * 4)},
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1, 2], providers=["boosty"], allow_stale=True
        )
        assert result[1]["boosty"].tier_rank == 2
        assert result[2]["boosty"].state == SubscriptionState.UNKNOWN
        assert strategy.calls == []
        assert store.upserts == []

    async def test_force_refresh_wins_over_allow_stale(self):
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2, age_seconds=1)},
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"], force_refresh=True, allow_stale=True
        )
        assert result[1]["boosty"].state == SubscriptionState.INACTIVE
        assert strategy.calls


class TestChallengeCodeIsAuthoritative(IsolatedAsyncioTestCase):
    async def test_live_redeemed_code_is_never_refetched(self):
        """A redeemed code has nothing to re-poll: it stays valid until its own
        `expires_at`, regardless of the TTL used for pull-based providers."""
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={
                (1, "boosty"): _stored(
                    SubscriptionState.ACTIVE,
                    tier=3,
                    age_seconds=SUBSCRIPTION_TTL_SECONDS * 10,
                    expires_in=86_400,
                    source=SubscriptionSource.CHALLENGE_CODE,
                )
            },
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].tier_rank == 3
        assert strategy.calls == []

    async def test_expired_code_falls_back_to_live_resolution(self):
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={
                (1, "boosty"): _stored(
                    SubscriptionState.ACTIVE,
                    tier=3,
                    expires_in=-1,
                    source=SubscriptionSource.CHALLENGE_CODE,
                )
            },
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"]
        )
        assert result[1]["boosty"].tier_rank == 1

    async def test_force_refresh_still_respects_a_live_code(self):
        """Check-in forces a refresh of pull-based providers, but a redeemed code
        is already conclusive — refetching Discord must not revoke it."""
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={
                (1, "boosty"): _stored(
                    SubscriptionState.ACTIVE,
                    tier=3,
                    expires_in=86_400,
                    source=SubscriptionSource.CHALLENGE_CODE,
                )
            },
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty"], force_refresh=True
        )
        assert result[1]["boosty"].tier_rank == 3
        assert strategy.calls == []


class TestBatching(IsolatedAsyncioTestCase):
    async def test_one_entitlement_query_for_every_provider(self):
        """Discord buckets rate limits per guild; the DB read must not fan out
        per provider either."""
        store = _FakeStore(
            configs={
                "boosty": _enabled("boosty"),
                "twitch": _enabled("twitch", {"broadcaster_id": "1"}),
            }
        )
        strategies = {
            "boosty": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1)),
            "twitch": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1)),
        }
        await _resolver(store, strategies).resolve(
            workspace_id=WS, auth_user_ids=[1, 2, 3], providers=["boosty", "twitch"]
        )
        assert len(store.load_calls) == 1
        assert len(store.config_calls) == 1
        assert set(store.load_calls[0][2]) == {"boosty", "twitch"}

    async def test_strategy_receives_every_stale_user_in_one_call(self):
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1, 2, 3], providers=["boosty"]
        )
        assert len(strategy.calls) == 1
        assert strategy.calls[0][1] == (1, 2, 3)

    async def test_only_stale_users_are_sent_to_the_provider(self):
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(2, "boosty"): _stored(SubscriptionState.ACTIVE, tier=1, age_seconds=1)},
        )
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1, 2, 3], providers=["boosty"]
        )
        assert strategy.calls[0][1] == (1, 3)

    async def test_every_stale_user_persists_in_one_write(self):
        """The write side must batch exactly like the read side does: N stale
        users behind one provider is one round trip, not N."""
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        strategy = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1, 2, 3], providers=["boosty"]
        )
        assert store.upsert_many_calls == [(WS, "boosty", 3)]
        assert {u[1] for u in store.upserts} == {1, 2, 3}


class TestTotalCoverage(IsolatedAsyncioTestCase):
    async def test_every_user_and_provider_appears_in_the_result(self):
        """`evaluate_requirement` reads a missing key as UNDETERMINED, so a gap
        here would be indistinguishable from a real provider outage."""
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        strategy = _FakeStrategy(verdicts={1: _verdict(SubscriptionState.ACTIVE, 1)})
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1, 2], providers=["boosty", "twitch"]
        )
        assert set(result) == {1, 2}
        for uid in (1, 2):
            assert set(result[uid]) == {"boosty", "twitch"}

    async def test_user_the_strategy_omitted_becomes_unknown(self):
        store = _FakeStore(configs={"boosty": _enabled("boosty")})
        strategy = _FakeStrategy(verdicts={1: _verdict(SubscriptionState.ACTIVE, 1)})
        result = await _resolver(store, {"boosty": strategy}).resolve(
            workspace_id=WS, auth_user_ids=[1, 2], providers=["boosty"]
        )
        assert result[2]["boosty"].state == SubscriptionState.UNKNOWN


class TestProviderFailureIsolation(IsolatedAsyncioTestCase):
    async def test_strategy_exception_yields_unknown_for_that_provider_only(self):
        store = _FakeStore(
            configs={
                "boosty": _enabled("boosty"),
                "twitch": _enabled("twitch", {"broadcaster_id": "1"}),
            }
        )
        strategies = {
            "boosty": _FakeStrategy(error=RuntimeError("discord exploded")),
            "twitch": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1)),
        }
        result = await _resolver(store, strategies).resolve(
            workspace_id=WS, auth_user_ids=[1], providers=["boosty", "twitch"]
        )
        assert result[1]["boosty"].state == SubscriptionState.UNKNOWN
        assert result[1]["boosty"].evidence["reason"] == "strategy_error"
        assert result[1]["twitch"].state == SubscriptionState.ACTIVE

    async def test_a_crashed_strategy_is_not_persisted(self):
        """An outage must not overwrite the last known good verdict."""
        store = _FakeStore(
            configs={"boosty": _enabled("boosty")},
            stored={(1, "boosty"): _stored(SubscriptionState.ACTIVE, tier=2, age_seconds=SUBSCRIPTION_TTL_SECONDS + 1)},
        )
        strategies = {"boosty": _FakeStrategy(error=RuntimeError("boom"))}
        await _resolver(store, strategies).resolve(workspace_id=WS, auth_user_ids=[1], providers=["boosty"])
        assert store.upserts == []


class TestEvaluateRequirement(IsolatedAsyncioTestCase):
    async def _evaluate(self, blob, *, stored=None, configs=None, strategies=None):
        store = _FakeStore(configs=configs or {}, stored=stored or {})
        resolver = _resolver(store, strategies or {})
        return await resolver.evaluate(workspace_id=WS, auth_user_ids=[1], requirement=parse_requirement(blob))

    async def test_empty_requirement_is_satisfied_without_touching_the_store(self):
        store = _FakeStore()
        outcomes = await _resolver(store, {}).evaluate(
            workspace_id=WS, auth_user_ids=[1], requirement=parse_requirement({})
        )
        assert outcomes[1][0] is Outcome.SATISFIED
        assert store.load_calls == []

    async def test_any_mode_passes_on_one_satisfied_provider(self):
        outcomes = await self._evaluate(
            {"mode": "any", "requirements": [{"provider": "boosty"}, {"provider": "twitch"}]},
            configs={
                "boosty": _enabled("boosty"),
                "twitch": _enabled("twitch", {"broadcaster_id": "1"}),
            },
            strategies={
                "boosty": _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE)),
                "twitch": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1)),
            },
        )
        assert outcomes[1][0] is Outcome.SATISFIED

    async def test_any_mode_with_refusal_and_outage_does_not_block(self):
        """The headline regression: an unconfigured Twitch must not turn a
        Boosty refusal into a hard block."""
        outcomes = await self._evaluate(
            {"mode": "any", "requirements": [{"provider": "boosty"}, {"provider": "twitch"}]},
            configs={"boosty": _enabled("boosty")},
            strategies={"boosty": _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE))},
        )
        outcome, verdicts = outcomes[1]
        assert outcome is Outcome.UNDETERMINED
        assert outcome.blocks_admission is False
        assert verdicts["twitch"].state == SubscriptionState.UNKNOWN

    async def test_all_mode_blocks_on_one_refusal(self):
        outcomes = await self._evaluate(
            {"mode": "all", "requirements": [{"provider": "boosty"}, {"provider": "twitch"}]},
            configs={
                "boosty": _enabled("boosty"),
                "twitch": _enabled("twitch", {"broadcaster_id": "1"}),
            },
            strategies={
                "boosty": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1)),
                "twitch": _FakeStrategy(default=_verdict(SubscriptionState.INACTIVE)),
            },
        )
        assert outcomes[1][0].blocks_admission is True

    async def test_threshold_is_enforced_per_provider(self):
        outcomes = await self._evaluate(
            {"mode": "all", "requirements": [{"provider": "boosty", "min_tier_rank": 3}]},
            configs={"boosty": _enabled("boosty")},
            strategies={"boosty": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))},
        )
        assert outcomes[1][0] is Outcome.REFUSED

    async def test_returns_per_provider_verdicts_for_the_ui(self):
        """The UI renders a chip per provider; re-resolving for display would
        double every provider call."""
        outcomes = await self._evaluate(
            {"mode": "any", "requirements": [{"provider": "boosty"}]},
            configs={"boosty": _enabled("boosty")},
            strategies={"boosty": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 2))},
        )
        _outcome, verdicts = outcomes[1]
        assert verdicts["boosty"].tier_rank == 2

    async def test_only_required_providers_are_resolved(self):
        store = _FakeStore(
            configs={
                "boosty": _enabled("boosty"),
                "twitch": _enabled("twitch", {"broadcaster_id": "1"}),
            }
        )
        twitch = _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1))
        resolver = _resolver(
            store,
            {"boosty": _FakeStrategy(default=_verdict(SubscriptionState.ACTIVE, 1)), "twitch": twitch},
        )
        await resolver.evaluate(
            workspace_id=WS,
            auth_user_ids=[1],
            requirement=parse_requirement({"requirements": [{"provider": "boosty"}]}),
        )
        assert twitch.calls == []


def _code_config(*, method: str, expires_in: int | None = None) -> dict:
    return {
        "verification_method": method,
        "codes": [
            {
                "code_sha256": "a" * 64,
                "tier_rank": 1,
                "expires_at": None if expires_in is None else (NOW + timedelta(seconds=expires_in)).isoformat(),
            }
        ],
    }


class TestAcceptedCodeProviders(IsolatedAsyncioTestCase):
    """Drives the check-in code field AND the registration gate's deferral.

    A provider named here is one the registration gate will NOT refuse, so a
    false positive silently disables signup-time gating for that provider.
    """

    async def _accepted(self, configs, *, providers=("boosty",)):
        resolver = _resolver(_FakeStore(configs=configs), {})
        return await resolver.accepted_code_providers(workspace_id=WS, providers=list(providers))

    async def test_code_only_with_a_live_code_is_accepted(self):
        configs = {"boosty": _enabled("boosty", _code_config(method="code"))}
        assert await self._accepted(configs) == {"boosty"}

    async def test_permissive_method_also_accepts(self):
        configs = {"boosty": _enabled("boosty", _code_config(method="any"))}
        assert await self._accepted(configs) == {"boosty"}

    async def test_live_only_never_accepts(self):
        configs = {"boosty": _enabled("boosty", _code_config(method="live"))}
        assert await self._accepted(configs) == set()

    async def test_no_codes_configured_is_not_accepted(self):
        """Choosing a code-accepting method and configuring nothing takes no paste."""
        configs = {"boosty": _enabled("boosty", {"verification_method": "any"})}
        assert await self._accepted(configs) == set()

    async def test_only_expired_codes_are_not_accepted(self):
        configs = {"boosty": _enabled("boosty", _code_config(method="code", expires_in=-1))}
        assert await self._accepted(configs) == set()

    async def test_a_disabled_provider_is_not_accepted(self):
        configs = {"boosty": ProviderConfigRow(provider="boosty", enabled=False, config=_code_config(method="code"))}
        assert await self._accepted(configs) == set()

    async def test_no_providers_asked_skips_the_query(self):
        store = _FakeStore()
        assert await _resolver(store, {}).accepted_code_providers(workspace_id=WS, providers=[]) == set()
        assert store.config_calls == []
