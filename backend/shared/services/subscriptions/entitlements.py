"""Resolve and compose subscription entitlements.

Public face of the subscription module. Two entry points:

- ``SubscriptionResolver.resolve`` -- batched raw verdicts, keyed
  ``{auth_user_id: {provider: verdict}}``. Shape deliberately mirrors
  ``shared.services.profile_visibility.resolve_profiles_open``, widened by one
  dimension because a tournament may require several providers at once.
- ``SubscriptionResolver.evaluate`` -- folds those verdicts through the Kleene
  composition in ``shared.services.subscriptions.requirement`` and returns the composed
  ``Outcome`` **alongside** the per-provider verdicts, so the UI can render a chip
  per provider without a second round of provider calls.

Two invariants worth keeping:

1. **Total coverage.** Every requested user appears in the outer dict and every
   requested provider in each inner dict. ``evaluate_requirement`` reads a missing
   key as ``UNDETERMINED``, so a gap here would be indistinguishable from a real
   outage.
2. **A failure never overwrites a good verdict.** A crashed strategy yields
   ``unknown`` for that provider and persists nothing, so the last known state
   survives the outage.

Persistence and live provider calls are injected (``EntitlementStore``,
``strategies``) so the whole decision table is testable without a database or a
network. An optional ``CheckLogSink`` appends the attempt to the collection
history; it is a *third* boundary rather than a method on ``EntitlementStore``
because the two have different contracts — the store holds one mutable
current-state row per (workspace, user, provider), the sink is append-only and
never read back by admission.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from loguru import logger

from shared.core.enums import SubscriptionCheckState, SubscriptionCollectionSource
from shared.services.subscriptions import (
    Outcome,
    SubscriptionRequirement,
    SubscriptionSource,
    SubscriptionState,
    SubscriptionVerdict,
    accepts_code,
    accepts_live,
    accepts_source,
    evaluate_requirement,
    parse_requirement,
    parse_verification_method,
)
from shared.services.subscriptions.challenge_code import has_live_code

__all__ = (
    "SUBSCRIPTION_TTL_SECONDS",
    "CheckLogSink",
    "EntitlementStore",
    "ProviderConfigRow",
    "ProviderStrategy",
    "StoredEntitlement",
    "SubscriptionEventSink",
    "SubscriptionResolver",
)

SUBSCRIPTION_TTL_SECONDS: Final = 15 * 60


@dataclass(frozen=True, slots=True)
class ProviderConfigRow:
    provider: str
    enabled: bool
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredEntitlement:
    """A persisted verdict, as read back from ``subscriptions.entitlement``."""

    state: str
    tier_rank: int | None
    tier_label: str | None
    source: str | None
    checked_at: datetime | None
    expires_at: datetime | None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_verdict(self) -> SubscriptionVerdict:
        return SubscriptionVerdict(
            state=self.state,  # type: ignore[arg-type]
            tier_rank=self.tier_rank,
            tier_label=self.tier_label,
            source=self.source or "stored",
            checked_at=self.checked_at or datetime.now(UTC),
            expires_at=self.expires_at,
            evidence=dict(self.evidence),
        )


class EntitlementStore(Protocol):
    """Data-access boundary. One call per concern, never one per provider."""

    async def load_configs(self, workspace_id: int, providers: Sequence[str]) -> dict[str, ProviderConfigRow]: ...

    async def load_requirement(self, workspace_id: int) -> dict[str, Any] | None: ...

    async def load_entitlements(
        self,
        workspace_id: int,
        auth_user_ids: Sequence[int],
        providers: Sequence[str],
    ) -> dict[tuple[int, str], StoredEntitlement]: ...

    async def upsert(
        self,
        workspace_id: int,
        auth_user_id: int,
        provider: str,
        verdict: SubscriptionVerdict,
    ) -> None: ...

    async def upsert_many(
        self,
        workspace_id: int,
        provider: str,
        verdicts: Mapping[int, SubscriptionVerdict],
    ) -> None:
        """One round trip for every ``auth_user_id -> verdict`` in ``verdicts``.

        The one place ``resolve`` needs to write more than a single row: a cold
        cache (TTL expiring for a whole workspace at once, or the first read
        after a tournament turns a subscription requirement on) can leave
        dozens of users stale for the same provider in one pass. ``upsert``
        (singular) stays for genuinely single-row writes -- challenge-code
        redemption is exactly one user, one provider, one verdict.
        """
        ...


class ProviderStrategy(Protocol):
    """Live resolution for one provider across a batch of users.

    The strategy owns its own identity lookup (which OAuth connection maps to
    which external id), so the resolver stays purely about config and caching.
    """

    async def resolve_many(
        self, *, config: dict[str, Any], auth_user_ids: Sequence[int]
    ) -> dict[int, SubscriptionVerdict]: ...


class CheckLogSink(Protocol):
    """Append-only history boundary — one row per live provider resolution.

    Separate from ``EntitlementStore`` on purpose: the store answers "what is
    their state now?" from a single row it overwrites, this answers "what
    happened, and when?" and is never read back by an admission decision. A
    resolver without a sink behaves exactly as before.
    """

    async def log_check(
        self,
        *,
        workspace_id: int,
        auth_user_id: int,
        provider: str,
        state: str,
        source: str,
        verdict: SubscriptionVerdict | None = None,
        error: str | None = None,
    ) -> None: ...


class SubscriptionEventSink(Protocol):
    """Realtime "something changed" boundary -- one signal per resolve pass.

    Separate from ``CheckLogSink``: that records every ATTEMPT (an unchanged
    re-check included) because it is the audit trail, while this fires only when a
    verdict actually moved, because it exists to invalidate a client cache. Wiring
    it to attempts instead would make the collector's every-tick ``force_refresh``
    sweep refetch every open admin page forever.

    A resolver without a sink behaves exactly as before.
    """

    async def subscriptions_updated(self, *, workspace_id: int, trigger: str) -> None: ...


class SubscriptionResolver:
    def __init__(
        self,
        *,
        store: EntitlementStore,
        strategies: Mapping[str, ProviderStrategy],
        now: Callable[[], datetime] | None = None,
        ttl_seconds: int = SUBSCRIPTION_TTL_SECONDS,
        log_sink: CheckLogSink | None = None,
        event_sink: SubscriptionEventSink | None = None,
    ) -> None:
        self._store = store
        self._strategies = strategies
        self._now = now or (lambda: datetime.now(UTC))
        self._ttl_seconds = ttl_seconds
        self._log_sink = log_sink
        self._event_sink = event_sink

    # ── raw verdicts ──────────────────────────────────────────────────────────

    async def resolve(
        self,
        *,
        workspace_id: int,
        auth_user_ids: Sequence[int],
        providers: Sequence[str],
        force_refresh: bool = False,
        source: str = SubscriptionCollectionSource.scheduled,
    ) -> dict[int, dict[str, SubscriptionVerdict]]:
        user_ids = list(dict.fromkeys(auth_user_ids))
        wanted = list(dict.fromkeys(providers))
        if not user_ids or not wanted:
            return {}

        configs = await self._store.load_configs(workspace_id, wanted)
        stored = await self._store.load_entitlements(workspace_id, user_ids, wanted)

        out: dict[int, dict[str, SubscriptionVerdict]] = {uid: {} for uid in user_ids}
        # One realtime signal for the whole pass, folded here rather than per user:
        # a sweep that flips 40 verdicts must cost every open admin page one
        # refetch, not forty. `resolve` is already scoped to a single workspace,
        # so a bool is the whole bookkeeping.
        changed = False

        for provider in wanted:
            unusable = self._unusable_reason(provider, configs.get(provider))
            if unusable is not None:
                for uid in user_ids:
                    out[uid][provider] = self._unknown(unusable)
                continue

            config = configs[provider].config
            method = parse_verification_method(config)

            stale: list[int] = []
            for uid in user_ids:
                row = stored.get((uid, provider))
                # A stored verdict whose source the chosen method no longer accepts
                # is treated as ABSENT, not merely ignored: otherwise narrowing the
                # method could never revoke a redeemed code, which is deliberately
                # never re-polled.
                if (
                    row is not None
                    and accepts_source(method, row.source)
                    and self._is_usable(row, force_refresh=force_refresh)
                ):
                    out[uid][provider] = row.to_verdict()
                else:
                    stale.append(uid)

            if not stale:
                continue

            if not accepts_live(method):
                # Code-only: the only admissible proof is a redeemed code, and every
                # stale user demonstrably has none. This is a real refusal, not an
                # outage — answering `unknown` here is exactly what used to make the
                # gate fail open and admit everybody. Nothing is persisted: it is
                # derived from the absence of a row, and a redemption overwrites it.
                for uid in stale:
                    out[uid][provider] = self._no_code_redeemed()
                continue

            try:
                fresh = await self._strategies[provider].resolve_many(config=config, auth_user_ids=stale)
            except Exception as exc:
                # Isolate the blast radius: this provider is unknown for these
                # users, nothing is persisted, every other provider is untouched.
                # The history log is the one exception — an outage that leaves no
                # trace is indistinguishable from a provider nobody configured.
                for uid in stale:
                    out[uid][provider] = self._unknown("strategy_error")
                    await self._log(
                        workspace_id=workspace_id,
                        auth_user_id=uid,
                        provider=provider,
                        state=SubscriptionCheckState.error,
                        source=source,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                continue

            to_persist: dict[int, SubscriptionVerdict] = {}
            for uid in stale:
                verdict = fresh.get(uid)
                if verdict is None:
                    # The strategy declined to answer. Treated as unknown rather
                    # than silently omitted -- see the total-coverage invariant.
                    out[uid][provider] = self._unknown("not_resolved")
                    await self._log(
                        workspace_id=workspace_id,
                        auth_user_id=uid,
                        provider=provider,
                        state=SubscriptionCheckState.unknown,
                        source=source,
                        verdict=out[uid][provider],
                    )
                    continue
                out[uid][provider] = verdict
                changed = changed or self._differs(stored.get((uid, provider)), verdict)
                to_persist[uid] = verdict
                await self._log(
                    workspace_id=workspace_id,
                    auth_user_id=uid,
                    provider=provider,
                    state=verdict.state,
                    source=source,
                    verdict=verdict,
                )

            # One write for the whole stale batch instead of one per user: a
            # cold cache (everyone's TTL expiring together, or the very first
            # list read after a tournament turns subscriptions on) used to cost
            # N sequential round trips here -- see EntitlementStore's docstring
            # ("one call per concern, never one per provider" -- this closes
            # the one place that promise didn't hold).
            if to_persist:
                await self._store.upsert_many(workspace_id, provider, to_persist)

        if changed:
            await self._emit_updated(workspace_id=workspace_id, trigger=source)

        return out

    # ── composed admission answer ─────────────────────────────────────────────

    async def evaluate(
        self,
        *,
        workspace_id: int,
        auth_user_ids: Sequence[int],
        requirement: SubscriptionRequirement,
        force_refresh: bool = False,
        source: str = SubscriptionCollectionSource.scheduled,
    ) -> dict[int, tuple[Outcome, dict[str, SubscriptionVerdict]]]:
        user_ids = list(dict.fromkeys(auth_user_ids))
        if not requirement.requirements:
            return {uid: (Outcome.SATISFIED, {}) for uid in user_ids}

        verdicts = await self.resolve(
            workspace_id=workspace_id,
            auth_user_ids=user_ids,
            providers=requirement.providers,
            force_refresh=force_refresh,
            source=source,
        )
        return {
            uid: (evaluate_requirement(requirement, verdicts.get(uid, {})), verdicts.get(uid, {})) for uid in user_ids
        }

    async def accepted_code_providers(self, *, workspace_id: int, providers: Sequence[str]) -> set[str]:
        """Providers where pasting a challenge code can currently help.

        Its own query rather than a by-product of ``resolve``: only the patron's own
        status read needs it (admins never redeem), and the alternative — widening
        ``evaluate``'s return type — would ripple through every bulk read that has no
        use for it.

        "Can help" is literal: the method must accept codes AND at least one code must
        still be live. A provider whose codes all expired takes no paste, and the
        registration gate defers a refusal for exactly this set — so a loose answer
        here would defer forever on a rule nobody can satisfy by code.
        """
        wanted = list(dict.fromkeys(providers))
        if not wanted:
            return set()
        now = self._now()
        configs = await self._store.load_configs(workspace_id, wanted)
        return {
            provider
            for provider, row in configs.items()
            if row.enabled
            and accepts_code(parse_verification_method(row.config))
            and has_live_code(row.config, now=now)
        }

    async def load_requirement(self, *, workspace_id: int) -> SubscriptionRequirement | None:
        """The workspace's enforceable rule, or ``None`` when there is nothing to enforce.

        Here rather than on the caller for the same reason as ``accepted_code_providers``:
        it is a workspace-scoped question that is not ``evaluate``, and routing it through
        the store keeps every gate free of both the query and the parse.

        Fails OPEN on a malformed blob, matching what every call site did inline before
        this moved: refusing every patron mid-tournament because one config row is bad is
        the worse failure. An empty rule collapses to ``None`` too, so "toggle on, nothing
        configured" stays the documented no-op that never calls a provider.

        The caught set is wider than ``parse_requirement``'s documented ``ValueError``
        (unknown ``mode``) on purpose, because the blob is arbitrary stored JSON and only
        its *shape* is validated on write: ``{"requirements": "boosty"}`` iterates the
        string and raises ``AttributeError`` on ``row.get``, ``{"requirements": 5}``
        raises ``TypeError`` on the ``for``. This function is the single chokepoint the
        whole admission stack trusts -- check-in, the participants list and the
        registration form all route through it -- so letting either escape would turn one
        bad row into three 500s, which is exactly the promise above.

        Failing open is silent and PERMANENT -- the gate keeps admitting everybody for as
        long as the row stays bad -- so the swallow logs, mirroring the collector's own
        skip warning (``subscription_collection.service``). It is also the only signal
        distinguishing bad data from a coding error inside ``parse_requirement``, since
        the caught set is wide enough to hide an ``AttributeError`` raised by a genuine
        bug rather than by a string blob.
        """
        blob = await self._store.load_requirement(workspace_id)
        if not blob:
            return None
        try:
            requirement = parse_requirement(blob)
        except (ValueError, TypeError, AttributeError):
            logger.warning(
                "Malformed subscription requirement for workspace_id={}: failing open, "
                "nothing will be enforced until the row is fixed",
                workspace_id,
            )
            return None
        return requirement if requirement.requirements else None

    # ── internals ─────────────────────────────────────────────────────────────

    async def _log(
        self,
        *,
        workspace_id: int,
        auth_user_id: int,
        provider: str,
        state: str,
        source: str,
        verdict: SubscriptionVerdict | None = None,
        error: str | None = None,
    ) -> None:
        """Append one attempt to the collection history, if a sink is wired.

        Swallows sink failures: history is diagnostics, and losing a log row must
        never turn into a failed admission decision or an aborted collector tick.
        """
        if self._log_sink is None:
            return
        try:
            await self._log_sink.log_check(
                workspace_id=workspace_id,
                auth_user_id=auth_user_id,
                provider=provider,
                state=state,
                source=source,
                verdict=verdict,
                error=error,
            )
        except Exception:  # pragma: no cover - defensive; see docstring
            pass

    @staticmethod
    def _differs(previous: StoredEntitlement | None, verdict: SubscriptionVerdict) -> bool:
        """Whether this verdict is news, i.e. worth a realtime signal.

        Compares only what a reader can see -- state, tier and how it was proven --
        never ``checked_at``/``evidence``: every forced re-check rewrites those, so
        including them would make the collector's every-tick sweep "change"
        everything and defeat the point of the flag.

        No stored row at all IS news: it is the patron's first verdict.
        """
        if previous is None:
            return True
        return (previous.state, previous.tier_rank, previous.source) != (
            verdict.state,
            verdict.tier_rank,
            verdict.source,
        )

    async def _emit_updated(self, *, workspace_id: int, trigger: str) -> None:
        """Signal the workspace that entitlements moved, if a sink is wired.

        Swallows failures for the same reason as ``_log``: a client that misses an
        invalidation refetches on its next reconnect, while an admission decision
        that fails because staging an event blew up is a real outage.
        """
        if self._event_sink is None:
            return
        try:
            await self._event_sink.subscriptions_updated(workspace_id=workspace_id, trigger=trigger)
        except Exception:  # pragma: no cover - defensive; see docstring
            pass

    def _unusable_reason(self, provider: str, config: ProviderConfigRow | None) -> str | None:
        """Why this provider cannot answer at all, or ``None`` if it can.

        Every branch here is the ORGANIZER's problem, so all of them resolve to
        ``unknown`` (fail open) -- never to a refusal.
        """
        if config is None:
            return "provider_not_configured"
        if not config.enabled:
            return "provider_disabled"

        method = parse_verification_method(config.config)
        if not accepts_live(method):
            # Code-only needs no strategy at all, so a missing one is irrelevant.
            # What IS fatal is choosing code-only and configuring no codes: the
            # requirement becomes unsatisfiable by anyone, which is an organizer
            # error and therefore fails open like every other one.
            if not (config.config or {}).get("codes"):
                return "no_codes_configured"
            return None

        if provider not in self._strategies:
            return "no_strategy_for_provider"
        return None

    def _is_usable(self, row: StoredEntitlement, *, force_refresh: bool) -> bool:
        now = self._now()
        expired = row.expires_at is not None and row.expires_at <= now

        # A redeemed challenge code has nothing to re-poll: it is conclusive until
        # its own expiry. `force_refresh` (check-in) must not revoke it by asking
        # Discord, which knows nothing about codes.
        if row.source == SubscriptionSource.CHALLENGE_CODE:
            return not expired

        if force_refresh or expired or row.checked_at is None:
            return False
        return (now - row.checked_at).total_seconds() < self._ttl_seconds

    def _unknown(self, reason: str) -> SubscriptionVerdict:
        now = self._now()
        return SubscriptionVerdict(
            state=SubscriptionState.UNKNOWN,
            tier_rank=None,
            tier_label=None,
            source="resolver",
            checked_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
            evidence={"reason": reason},
        )

    def _no_code_redeemed(self) -> SubscriptionVerdict:
        """A real refusal under code-only verification.

        ``inactive``, not ``unknown``: the patron simply has not redeemed a code,
        and there is nothing to be uncertain about. This is the branch that makes
        code-only actually gate anything.
        """
        now = self._now()
        return SubscriptionVerdict(
            state=SubscriptionState.INACTIVE,
            tier_rank=None,
            tier_label=None,
            source=SubscriptionSource.CHALLENGE_CODE,
            checked_at=now,
            expires_at=None,
            evidence={"reason": "no_code_redeemed"},
        )
