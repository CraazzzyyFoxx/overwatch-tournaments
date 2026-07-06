"""One-time Redis link-intent: carries a linking user across the apex bounce.

Account *linking* (attaching an additional OAuth provider to an existing
account) that starts on a workspace custom domain runs its OAuth round-trip
at the platform apex -- there is only ever ONE fixed ``redirect_uri``
registered with each provider (see ``oauth_service.generate_oauth_url``). The
apex callback can normally identify the linking user from a cookie set by
the SAME callback earlier (``Domain=.owt``, readable on the apex and every
``.owt`` subdomain) -- but a custom domain's session cookie is host-only
(different registrable domain, unreadable at the apex), so that path is
unavailable there (see ``oauth_flows.link``).

This module hands the apex callback an alternative, tightly-scoped
authenticated source: the custom domain's OWN frontend route (which CAN read
its own host-only cookie) mints an opaque, single-use, short-lived nonce
bound to that user (``issue``), carries it through the apex bounce and into
the HMAC-signed OAuth ``state`` (``oauth_service.encode_state``), and the
apex callback redeems it (``redeem``) to resolve who is linking.

SECURITY: a stateless signed token here (e.g. ``HMAC({user_id, exp})``) would
be REPLAYABLE -- it transits a redirect URL (browser history, referrer,
proxy/access logs) before ever being signed into the OAuth state, so anyone
who captures it within its TTL could start their OWN OAuth flow with the
captured link-intent and link their own provider account to the victim's
user (account takeover). A single-use Redis nonce closes this: ``redeem``
uses ``GETDEL`` so the read and the delete are one atomic op -- a nonce can
be consumed at most once, with no window for a second, concurrent redeem to
also succeed. The TTL (120s) only bounds how long a captured-but-unused
nonce stays dangerous; single-use is what actually stops replay.
"""

from __future__ import annotations

import json
import secrets

from loguru import logger
from redis.exceptions import RedisError

from src.core.redis import get_redis

_LINK_INTENT_PREFIX = "oauth:link-intent:"
_LINK_INTENT_TTL_SECONDS = 120


def _key(nonce: str) -> str:
    return f"{_LINK_INTENT_PREFIX}{nonce}"


async def issue(user_id: int) -> str:
    """Mint a one-time link-intent nonce bound to ``user_id``; return the nonce.

    ``user_id`` must already be resolved server-side from a verified access
    token by the caller (see ``oauth_flows.mint_link_intent``) -- this
    function never accepts or trusts a client-supplied id.

    Like ``sso_tickets.issue``, there is no safe fallback if Redis is
    unreachable: a nonce nobody could ever redeem is worse than an explicit
    failure, so this raises rather than minting one.
    """
    nonce = secrets.token_urlsafe(32)
    payload = json.dumps({"user_id": user_id})
    try:
        redis = get_redis()
        await redis.set(_key(nonce), payload, ex=_LINK_INTENT_TTL_SECONDS)
    except (RuntimeError, RedisError) as exc:
        logger.error(f"Failed to issue link-intent nonce: {exc}")
        raise
    return nonce


async def redeem(nonce: str) -> int | None:
    """Atomically read-and-delete a link-intent nonce; return its user id, or None.

    Fails CLOSED: a missing/blank nonce, an unknown nonce, an already-redeemed
    nonce (``GETDEL`` deletes on the first successful read), a naturally
    expired nonce, a corrupted payload, and an unreachable Redis are all
    indistinguishable from here -- every one of them returns None, and the
    caller (``oauth_flows.link``) treats that identically to "no linking user
    could be resolved" (fail closed, never falls back to an unauthenticated
    link).
    """
    if not nonce:
        return None
    try:
        redis = get_redis()
        raw = await redis.getdel(_key(nonce))
    except (RuntimeError, RedisError) as exc:
        logger.warning(f"Link-intent redeem unavailable, failing closed: {exc}")
        return None

    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return int(payload["user_id"])
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        logger.warning("Corrupted link-intent payload, discarding")
        return None
