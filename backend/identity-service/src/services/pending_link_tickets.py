"""One-time Redis pending-link ticket: hands a PROVIDER identity across the
custom-domain <-> apex boundary for account LINKING (Task 10R).

This mirrors ``sso_tickets`` (Task 8's login ticket) with the roles reversed.
The login ticket carries a SESSION forward so a custom domain can adopt it;
this ticket carries ONLY the just-exchanged OAuth PROVIDER identity -- never
a site user id -- because the linked-to site account can only be resolved
from a LIVE session, and the apex callback (where this is minted) never has
one for a custom-domain user (no shared cookie crosses that boundary; see
``oauth_flows.link``). The custom domain's own frontend route
(``/auth/link/complete``) redeems this ticket via ``rpc.identity.link_complete``
-- authenticated by ITS OWN live session -- and attaches the provider
identity to whichever user that bearer resolves to. See SECURITY INVARIANTS
1/2 in the Task 10R brief.

``redeem`` uses Redis ``GETDEL`` so the read and the delete are one atomic
op: a ticket can be redeemed at most once, and there is no window in which
two concurrent redeems could both succeed.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from loguru import logger
from redis.exceptions import RedisError

from src.core.redis import get_redis
from src.schemas.oauth import OAuthUserInfo

_TICKET_PREFIX = "link:ticket:"
_TICKET_TTL_SECONDS = 120


def _key(code: str) -> str:
    return f"{_TICKET_PREFIX}{code}"


async def issue(oauth_info: OAuthUserInfo, token_data: dict[str, Any]) -> str:
    """Mint a one-time ticket carrying ONLY the provider identity; return its
    opaque code.

    ``oauth_info`` is the already-exchanged provider profile (username,
    provider_user_id, email, ...) and ``token_data`` the provider's own OAuth
    tokens -- both needed later to call
    ``OAuthService.link_oauth_to_existing_user`` from ``link_complete``.
    Deliberately NEVER carries a site ``AuthUser`` id (SECURITY INVARIANT #2):
    there is no live session to resolve one from at mint time (see module
    docstring), and even if there were, deriving the linked-to user from
    anything other than a live session at redeem time is exactly the
    account-linking-hijack shape this task replaces.

    Like ``sso_tickets.issue``, this has no safe fallback if Redis is
    unreachable -- a ticket nobody could ever redeem is worse than an
    explicit failure, so this raises rather than minting one.
    """
    code = secrets.token_urlsafe(32)
    payload = json.dumps({"oauth_info": oauth_info.model_dump(mode="json"), "token_data": token_data})
    try:
        redis = get_redis()
        await redis.set(_key(code), payload, ex=_TICKET_TTL_SECONDS)
    except (RuntimeError, RedisError) as exc:
        logger.error(f"Failed to issue pending-link ticket: {exc}")
        raise
    return code


async def redeem(code: str) -> dict[str, Any] | None:
    """Atomically read-and-delete a ticket; return its ``{oauth_info, token_data}``
    payload dict, or None.

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
        logger.warning(f"Pending-link ticket redeem unavailable, failing closed: {exc}")
        return None

    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupted pending-link ticket payload, discarding")
        return None
