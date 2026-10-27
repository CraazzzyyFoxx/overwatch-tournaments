"""Per-actor rate limits for the public team-registration flows.

These are the only *authenticated* rate limits in the stack. The gateway's
``internal/ratelimit`` is per-IP, per-process and scoped to ``/api/auth/*``; nginx
provides a coarse outer layer. Neither bounds what one logged-in account can do,
which is exactly the surface the captain and invitee flows open.

**The fail direction is deliberately not uniform.**

* ``invite`` **fails closed.** Each call mints a bearer credential — a token whose
  holder can write a registration into someone else's roster — and, for a targeted
  invite, sends a notification. That makes it an amplifier, so losing Redis must not
  turn it into an unmetered one. The cost is real and accepted: during a Redis
  outage captains cannot invite.

* ``accept``/``decline`` **fail open**, matching
  :func:`assert_redeem_attempt_allowed` for challenge codes. The thing a limiter
  protects there is a 256-bit token against guessing, which is already infeasible;
  the limiter is defence in depth. Blocking legitimate invitees during a Redis blip
  is the worse outcome, and — unlike invite — a *successful* accept is
  self-limiting: one registration per player per tournament means the second one
  cannot succeed at all.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from loguru import logger
from redis.exceptions import RedisError

from shared.core.errors import ApiExc, ApiHTTPException

__all__ = (
    "ACCEPT_ATTEMPT_LIMIT",
    "ACCEPT_WINDOW_SECONDS",
    "INVITE_ATTEMPT_LIMIT",
    "INVITE_WINDOW_SECONDS",
    "TEAM_INVITE_TOTAL_CAP",
    "assert_accept_attempt_allowed",
    "assert_invite_attempt_allowed",
    "count_attempt",
)

#: A 12-slot roster (``MAX_TEAM_SIZE``) needs at most 11 invites; 30 leaves room
#: for declines and replacements while staying far below "notification amplifier".
INVITE_ATTEMPT_LIMIT = 30
INVITE_WINDOW_SECONDS = 600

#: Redemption attempts. Generous because a legitimate invitee may retry after
#: fixing a validation error in their own registration payload.
ACCEPT_ATTEMPT_LIMIT = 20
ACCEPT_WINDOW_SECONDS = 600

#: Covers what the slot reservation cannot. Reserving a slot caps
#: *concurrent* pending invites at the number of open slots, but says nothing about
#: churn: invite -> revoke -> invite in a loop stays within every slot rule. This
#: is a cumulative ceiling on invites ever created for one team, counting revoked
#: and declined ones, so the loop terminates even inside one rate-limit window.
TEAM_INVITE_TOTAL_CAP = 60

_redis_client: aioredis.Redis | None = None
_redis_broken = False


def _client() -> aioredis.Redis | None:
    """The shared client, or ``None`` when Redis cannot be constructed at all.

    ``None`` means "no limiter available" and each caller decides what that
    implies — it is NOT the same as an operation failing.
    """
    global _redis_client, _redis_broken
    if _redis_broken:
        return None
    if _redis_client is None:
        from src.core.config import settings

        try:
            _redis_client = aioredis.Redis.from_url(str(settings.redis_url), decode_responses=True)
        except Exception as exc:  # pragma: no cover - configuration failure
            _redis_broken = True
            logger.warning(f"team invite rate limit: redis client unavailable: {exc}")
            return None
    return _redis_client


def _too_many(code: str, msg: str) -> ApiHTTPException:
    return ApiHTTPException(status_code=429, detail=[ApiExc(msg=msg, code=code)])


def _unavailable(code: str, msg: str) -> ApiHTTPException:
    # 503, not 429: the actor did nothing wrong and a Retry-After style backoff is
    # the honest instruction. Returning 429 would tell them to slow down when the
    # real problem is ours.
    return ApiHTTPException(status_code=503, detail=[ApiExc(msg=msg, code=code)])


async def count_attempt(client: aioredis.Redis, key: str, window_seconds: int) -> int:
    """Count one hit on ``key`` and return the total in the current window.

    ``INCR`` then ``EXPIRE … NX`` in one MULTI: the window opens at the first hit,
    a later hit never extends it, and no failure between the two can leave a
    counter without an expiry -- which would rate-limit the actor forever. ``NX``
    also gives a key some earlier code left without a TTL its expiry back.
    Needs Redis 7+ (every compose file runs ``redis/redis-stack:latest``, 7.x).
    """
    async with client.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        attempts, _ = await pipe.execute()
    return int(attempts)


async def _consume(key: str, *, limit: int, window_seconds: int, redis: aioredis.Redis | None) -> bool | None:
    """Count one attempt. ``True`` = allowed, ``False`` = over limit, ``None`` = no
    verdict available (Redis missing or erroring)."""
    client = redis if redis is not None else _client()
    if client is None:
        return None
    try:
        attempts = await count_attempt(client, key, window_seconds)
    except RedisError as exc:
        logger.warning(f"team rate limit unavailable for {key}: {exc}")
        return None
    return attempts <= limit


async def assert_invite_attempt_allowed(
    *,
    tournament_id: int,
    auth_user_id: int,
    redis: aioredis.Redis | None = None,
) -> None:
    """Meter invite creation per actor per tournament. **Fails closed.**"""
    allowed = await _consume(
        f"regteam:invite:{tournament_id}:{auth_user_id}",
        limit=INVITE_ATTEMPT_LIMIT,
        window_seconds=INVITE_WINDOW_SECONDS,
        redis=redis,
    )
    if allowed is None:
        raise _unavailable(
            "rate_limit_unavailable",
            "Invites are temporarily unavailable. Please try again shortly.",
        )
    if not allowed:
        raise _too_many("invite_rate_limited", "Too many invites. Please wait before sending more.")


async def assert_accept_attempt_allowed(
    *,
    auth_user_id: int,
    redis: aioredis.Redis | None = None,
) -> None:
    """Meter invite redemption per actor. **Fails open** — see the module docstring.

    Not scoped to a tournament: the actor is redeeming a token that names its own
    team, so there is no tournament id to key on before the lookup, and keying on
    the account is the tighter bound anyway.
    """
    allowed = await _consume(
        f"regteam:accept:{auth_user_id}",
        limit=ACCEPT_ATTEMPT_LIMIT,
        window_seconds=ACCEPT_WINDOW_SECONDS,
        redis=redis,
    )
    if allowed is False:
        raise _too_many("accept_rate_limited", "Too many attempts. Please wait and try again.")
