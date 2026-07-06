"""One-time Redis SSO ticket: hands a session to a custom domain.

Cookies set while the OAuth flow runs on the platform apex are NOT readable
on a workspace's custom domain (different registrable domain) -- see
``oauth_flows.callback``. Instead, the apex callback mints an opaque,
short-lived, single-use ticket carrying the session tokens; the custom
domain's own frontend route redeems it via ``rpc.identity.sso_exchange``
(``serve.py``) and sets host-only cookies itself. The raw tokens never
appear in a URL -- only the opaque ticket does.

``redeem`` uses Redis ``GETDEL`` so the read and the delete are one atomic
op: a ticket can be redeemed at most once, and there is no window in which
two concurrent redeems could both succeed.
"""

from __future__ import annotations

import json
import secrets

from loguru import logger
from redis.exceptions import RedisError

from src.core.redis import get_redis

_TICKET_PREFIX = "sso:ticket:"
_TICKET_TTL_SECONDS = 60


def _key(code: str) -> str:
    return f"{_TICKET_PREFIX}{code}"


async def issue(access_token: str, refresh_token: str, redirect: str) -> str:
    """Mint a one-time ticket carrying the session tokens; return its opaque code.

    Unlike this service's other Redis-backed caches (which degrade
    gracefully because they're pure optimizations -- see ``session_cache``),
    a custom-domain OAuth callback has no fallback: cookies can't be set on
    the apex and read back on the custom domain, so the ticket IS the only
    way to deliver the session. If Redis is unreachable there is nothing
    safe to hand back, so this raises rather than minting a ticket nobody
    could ever redeem.
    """
    code = secrets.token_urlsafe(32)
    payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token, "redirect": redirect})
    try:
        redis = get_redis()
        await redis.set(_key(code), payload, ex=_TICKET_TTL_SECONDS)
    except (RuntimeError, RedisError) as exc:
        logger.error(f"Failed to issue SSO ticket: {exc}")
        raise
    return code


async def redeem(code: str) -> dict | None:
    """Atomically read-and-delete a ticket; return its payload, or None.

    Fails CLOSED: an unknown code, an already-redeemed code (``GETDEL``
    deletes on the first successful read), a naturally-expired code, and an
    unreachable Redis are all indistinguishable from here -- every one of
    them returns None, and the caller reports a single generic "invalid or
    expired ticket" regardless of which case it was.
    """
    if not code:
        return None
    try:
        redis = get_redis()
        raw = await redis.getdel(_key(code))
    except (RuntimeError, RedisError) as exc:
        logger.warning(f"SSO ticket redeem unavailable, failing closed: {exc}")
        return None

    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupted SSO ticket payload, discarding")
        return None
