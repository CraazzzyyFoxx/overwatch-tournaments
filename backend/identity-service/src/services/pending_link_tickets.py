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

Task 10R fix 1: the ticket alone is single-use but not browser-bound -- a
standalone GET redeem route has nothing stopping an attacker from running
their own link flow, capturing their own ticket, and luring a victim (who
has a live bearer session) into redeeming it -- attaching the ATTACKER's
provider identity to the VICTIM's account (account takeover). ``issue``
optionally stores a ``guard_hash`` (short key ``"lg"``) alongside the
provider identity; ``oauth_flows.link_complete`` requires the raw guard
cookie value at redemption and constant-time-compares its hash against this
field -- even given an otherwise-valid bearer -- before ever linking
anything. See ``oauth_flows``'s module docstring for the full rationale.
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


async def issue(oauth_info: OAuthUserInfo, token_data: dict[str, Any], *, guard_hash: str | None = None) -> str:
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

    ``guard_hash`` (Task 10R fix 1) is OPTIONAL here -- this module has no
    opinion on whether a caller should supply one; it just faithfully stores
    whatever it's given under the short key ``"lg"`` (omitted entirely when
    ``None``). The fail-closed "never issue a ticket for a custom-domain link
    with no guard hash" rule lives one layer up, in ``oauth_flows.link``
    (``_require_guard_hash_for_ticket``) -- by the time it reaches here in the
    real flow, ``guard_hash`` is always a non-empty string. It is later
    compared (constant-time, in ``oauth_flows.link_complete``) against the
    RAW guard cookie value presented at redemption -- the raw value itself is
    never stored anywhere, only this hash.

    Like ``sso_tickets.issue``, this has no safe fallback if Redis is
    unreachable -- a ticket nobody could ever redeem is worse than an
    explicit failure, so this raises rather than minting one.
    """
    code = secrets.token_urlsafe(32)
    ticket_payload: dict[str, Any] = {
        "oauth_info": oauth_info.model_dump(mode="json"),
        "token_data": token_data,
    }
    if guard_hash is not None:
        ticket_payload["lg"] = guard_hash
    payload = json.dumps(ticket_payload)
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
