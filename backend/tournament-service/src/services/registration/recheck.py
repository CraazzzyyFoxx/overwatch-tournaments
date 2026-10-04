"""The registrant's own "check my profile and subscriptions again" button.

Both checks normally run on their collectors' schedules; this asks for them now,
for one player. Each one spends a provider call (Twitch/Discord/Boosty, OverFast),
so the button sits behind a per-player cooldown.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from loguru import logger
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import SubscriptionCollectionSource
from shared.core.errors import ApiExc, ApiHTTPException
from src.services.registration._common import _common_service
from src.services.registration.admission import build_admission_resolver
from src.services.registration.subscription_status import _client as _redis_client
from src.services.tournament.events import enqueue_registration_rank_check

__all__ = ("RECHECK_COOLDOWN_SECONDS", "assert_recheck_allowed", "recheck_registration")

RECHECK_COOLDOWN_SECONDS = 60


async def assert_recheck_allowed(*, auth_user_id: int, redis: aioredis.Redis | None = None) -> None:
    """Start the player's cooldown, or raise 429 carrying the seconds left.

    Per user, not per tournament: the calls it spends are per user too. Fails open
    without Redis, like the redeem limiter: the rank fetches behind it keep their
    own per-minute ceiling, and a dead button during a Redis blip is the worse outcome.
    """
    client = redis or _redis_client()
    if client is None:
        return
    key = f"reg:recheck:{auth_user_id}"
    try:
        if await client.set(key, "1", nx=True, ex=RECHECK_COOLDOWN_SECONDS):
            return
        left = await client.ttl(key)
    except RedisError as exc:
        logger.warning(f"registration recheck cooldown unavailable, allowing: {exc}")
        return
    raise ApiHTTPException(
        status_code=429,
        detail=[ApiExc(msg="Checked recently. Please wait before checking again.", code="recheck_cooldown")],
        headers={"Retry-After": str(max(1, left))},
    )


async def recheck_registration(session: AsyncSession, registration: Any, *, auth_user_id: int) -> None:
    """Re-check whatever this tournament requires. The caller commits.

    Subscriptions are resolved live right here (``force_refresh``), so the next
    read of the registration already carries the new verdict. The profile check
    is a rank fetch parser-service runs off the outbox event, so it lands a little
    later.
    """
    form = await _common_service.get_registration_form(session, registration.tournament_id)
    if form is None:
        return
    if form.require_subscription:
        resolver = build_admission_resolver(session)
        rule = await resolver.load_requirement(workspace_id=form.workspace_id)
        if rule is not None:
            await resolver.evaluate(
                workspace_id=form.workspace_id,
                auth_user_ids=[auth_user_id],
                requirement=rule,
                force_refresh=True,
                source=SubscriptionCollectionSource.manual,
            )
    if form.require_open_profile:
        await enqueue_registration_rank_check(session, registration)
