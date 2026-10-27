"""The caller's own subscription standing, plus redemption rate limiting.

Feeds the registration form: one call returns the composed outcome and a
per-provider verdict so the form can render a chip on each account row. The
summary line above them (without which an ``any`` requirement reads as two
independent failures) is worded by the client from the form's
``subscription_requirement_json``, so it follows the reader's locale.

It also answers whether the registration gate would refuse this patron right now,
computed by the same composition the gate itself runs — the form must be able to
say "you cannot sign up yet" up front rather than let three steps be filled in
and answer 400 at submit.

Never forces a provider refresh -- the form polls this on render. Only the gates
force a fresh look, and only for the one acting user.
"""

from __future__ import annotations

from typing import Any, Protocol

import redis.asyncio as aioredis
from loguru import logger
from redis.exceptions import RedisError

from shared.core.errors import ApiExc, ApiHTTPException
from shared.services.subscriptions import (
    Outcome,
    SubscriptionRequirement,
    SubscriptionVerdict,
    evaluate_requirement,
)
from src.schemas.registration import (
    SubscriptionProviderVerdictRead,
    SubscriptionStatusRead,
)
from src.services.admission import AdmissionConfig, AdmissionStage
from src.services.registration.team_rate_limits import count_attempt

__all__ = (
    "REDEEM_ATTEMPT_LIMIT",
    "REDEEM_WINDOW_SECONDS",
    "assert_redeem_attempt_allowed",
    "subscription_status_for_user",
)

# Defence in depth: a challenge code is long enough not to be guessable, but the
# endpoint is still an oracle, so cap the attempts.
REDEEM_ATTEMPT_LIMIT = 10
REDEEM_WINDOW_SECONDS = 600


class RequirementEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        workspace_id: int,
        auth_user_ids: Any,
        requirement: SubscriptionRequirement,
        force_refresh: bool = False,
    ) -> dict[int, tuple[Outcome, dict[str, SubscriptionVerdict]]]: ...

    async def accepted_code_providers(self, *, workspace_id: int, providers: Any) -> set[str]: ...

    async def load_requirement(self, *, workspace_id: int) -> SubscriptionRequirement | None: ...


async def subscription_status_for_user(
    *,
    form: Any | None,
    auth_user_id: int,
    resolver: RequirementEvaluator,
) -> SubscriptionStatusRead:
    if form is None or not getattr(form, "require_subscription", False):
        return SubscriptionStatusRead(required=False)

    # The workspace owns the rule; the resolver owns the parse and fails open on a
    # malformed row, so "nothing enforceable" and "config is bad" both read as
    # not-required here rather than 500ing the registration form.
    requirement = await resolver.load_requirement(workspace_id=form.workspace_id)
    if requirement is None:
        return SubscriptionStatusRead(required=False)

    outcomes = await resolver.evaluate(
        workspace_id=form.workspace_id,
        auth_user_ids=[auth_user_id],
        requirement=requirement,
        force_refresh=False,
    )
    outcome, verdicts = outcomes[auth_user_id]
    # Which providers will actually take a code right now. Asked for separately
    # because `reason` cannot express it: under the permissive method an unlinked
    # patron reads `no_linked_discord_account`, yet a code would satisfy them too.
    code_providers = await resolver.accepted_code_providers(
        workspace_id=form.workspace_id, providers=requirement.providers
    )
    return SubscriptionStatusRead(
        required=True,
        mode=requirement.mode,
        outcome=outcome.value,
        # Same composition and opt-in as the registration gate: a check-in-staged
        # tournament never refuses sign-up, so promising a block here would disable a
        # submit the server accepts. Non-forcing, so a patron who just subscribed may
        # see a stale block for up to the entitlement TTL; the gate re-resolves live.
        # The stage comes from ``AdmissionConfig`` (the column's only reader), where an
        # absent or unrecognised value reads as ``check_in``: a typo must not start
        # refusing sign-ups.
        blocks_registration=(
            AdmissionConfig.from_form(form).subscription_stage is AdmissionStage.registration
            and evaluate_requirement(requirement, verdicts, deferred_providers=code_providers).blocks_admission
        ),
        verdicts={
            provider: SubscriptionProviderVerdictRead(
                state=verdict.state,
                tier_rank=verdict.tier_rank,
                tier_label=verdict.tier_label,
                reason=verdict.evidence.get("reason"),
                code_accepted=provider in code_providers,
            )
            for provider, verdict in verdicts.items()
        },
    )


async def assert_redeem_attempt_allowed(
    *,
    workspace_id: int,
    auth_user_id: int,
    redis: aioredis.Redis | None = None,
) -> None:
    """Raise 429 once a user exceeds ``REDEEM_ATTEMPT_LIMIT`` in the window.

    Fails OPEN when Redis is unavailable: a code long enough not to be guessable
    makes the limiter defence in depth, and blocking legitimate redemption during
    a Redis blip is the worse outcome. The blip is logged so it is not silent.
    """
    client = redis or _client()
    if client is None:
        return

    key = f"subs:redeem:{workspace_id}:{auth_user_id}"
    try:
        attempts = await count_attempt(client, key, REDEEM_WINDOW_SECONDS)
    except RedisError as exc:
        logger.warning(f"redeem rate limit unavailable, allowing attempt: {exc}")
        return

    if attempts > REDEEM_ATTEMPT_LIMIT:
        raise ApiHTTPException(
            status_code=429,
            detail=[ApiExc(code="subscription_redeem_rate_limited", msg="Too many attempts. Try again later.")],
        )


_redis_client: aioredis.Redis | None = None


def _client() -> aioredis.Redis | None:
    global _redis_client
    if _redis_client is None:
        from src.core.config import settings

        try:
            _redis_client = aioredis.Redis.from_url(str(settings.redis_url), decode_responses=True)
        except Exception as exc:  # pragma: no cover - configuration failure
            logger.warning(f"redeem rate limit disabled, redis unavailable: {exc}")
            return None
    return _redis_client
