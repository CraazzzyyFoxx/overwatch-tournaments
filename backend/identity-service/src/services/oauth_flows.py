"""RPC-callable OAuth flows (port of routes/oauth.py).

OAuth ``state`` is a signed, self-contained payload (HMAC + short TTL) that
carries the originating host/redirect/action, so it works across RPC calls
and across the ONE fixed apex callback with no shared storage for the CSRF
check itself. The one part that DOES need shared storage -- single-use nonce
replay protection -- is enforced here via Redis (see ``_consume_state_nonce``).
Callbacks return an ``OAuthCallbackResult`` (token + the decoded state
fields); the frontend handles its own redirect back to ``origin``. Provider
code-exchange does outbound HTTP from identity-svc.

The state alone is NOT proof the callback came from the same browser that
started the flow -- anyone can obtain a validly-signed state by calling
``get_url`` themselves (login/account-linking CSRF). ``callback``/``link``
close that gap by comparing ``sha256(csrf)`` (``csrf`` being the RAW value of
an HttpOnly cookie set when the flow started) against the hash embedded in
the state (see ``_verify_csrf_binding``); a missing or mismatched cookie is
rejected exactly like an invalid state (fail closed).

Task 10R fix 1 closes a SECOND, REVERSE CSRF one hop further out: the
``csrf``/state binding above only covers the apex start->callback leg. The
cross-domain tickets ``callback``/``link`` mint for a custom-domain origin
(``sso_tickets``/``pending_link_tickets``) are redeemed by a standalone GET
route on that custom domain with no equivalent binding -- so an attacker who
runs their OWN flow (with ``origin=<victim-domain>``), captures their OWN
ticket, and lures the victim into opening ``<victim-domain>/auth/sso?ticket=`` /
``/auth/link/complete?ticket=`` gets the VICTIM's browser to redeem the
ATTACKER's ticket (session fixation / account-takeover-via-linking). The fix
mirrors the csrf binding across that domain boundary: the frontend's
custom-domain apex bounce (``oauth-login.ts``) sets a host-only
``owt_xdomain_guard`` cookie (raw value ``G``, never leaves that cookie) and
signs ``H = sha256_hex(G)`` into the state as ``guard_hash`` (JSON key
``"lg"``, see ``OAuthService``). When a cross-domain ticket is issued, ``H``
is stored on the ticket itself (``ticket.lg``); redemption
(``sso_exchange``/``link_complete`` below) requires the raw ``G`` again and
constant-time-compares ``sha256_hex(G) == ticket.lg`` (``_verify_guard_binding``).
The attacker's ticket is bound to the ATTACKER's ``G`` (in the attacker's own
browser); the victim's browser never held that cookie (host-only, no
``domain`` attribute) and cannot be made to hold it without XSS, so
redemption fails closed. Issuance itself is fail-closed too: a ticket-mode
callback/link with no ``guard_hash`` on the verified state is a NEVER-ISSUE
error, not an unbound ticket (see ``callback``/``link`` below).
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlparse

from loguru import logger
from redis.exceptions import RedisError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import OAUTH_TO_SOCIAL
from shared.models.identity.oauth import OAuthConnection
from shared.models.identity.social import SocialAccount
from shared.tenancy.hostnames import is_platform_host, normalize_custom_domain
from src import models, schemas
from src.core.config import settings
from src.core.redis import get_redis
from src.services import pending_link_tickets, sso_tickets
from src.services.auth_service import AuthService
from src.services.oauth_service import OAuthService, StatePayload

# Actions a signed OAuth ``state`` may carry. "login" starts/continues a
# session; "link" attaches a provider to the CURRENT authenticated user.
_VALID_OAUTH_ACTIONS = frozenset({"login", "link"})

# Redis key prefix for single-use OAuth state nonces (replay protection).
_STATE_NONCE_PREFIX = "oauth:state-nonce:"


def list_providers() -> list[schemas.OAuthProviderAvailability]:
    return [schemas.OAuthProviderAvailability(provider=p) for p in OAuthService.get_available_providers()]


def _validate_origin(origin: str) -> None:
    """Reject an ``origin`` this service has no business signing into a state.

    ``origin`` is attacker-influenceable (it starts as whatever ``Host`` the
    browser hit), and it gets echoed straight back out of ``callback``/``link``
    for the frontend to redirect to -- so this is the open-redirect guard for
    the OAuth flow.

    identity-svc does not own the workspace database, so it cannot check
    ``origin`` against the actual set of verified custom domains. What it CAN
    do without a DB round-trip is reject anything that isn't even a
    well-formed host:

    - the platform apex or a ``.owt`` subdomain (``is_platform_host``) --
      trusted outright, same as Phase 1.
    - any other syntactically-valid FQDN (``normalize_custom_domain`` succeeds)
      -- accepted as a CANDIDATE custom domain. This is required: custom-domain
      login bounces its start to the apex and passes the real custom-domain
      origin as this parameter (see the frontend apex-bounce), so rejecting
      well-formed non-platform hosts here would break that flow entirely.
      Whether the host is an actual, VERIFIED custom domain is enforced
      elsewhere: the frontend's ``isAllowedOrigin`` allow-list, and --
      decisively -- the callback never hands a custom-domain origin raw
      tokens, only a workspace-bound one-time ticket (see ``sso_tickets``).
    - anything else (malformed URL, no host, ``javascript:``, empty string,
      etc.) is rejected with a 400 here.
    """
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid origin")
    host = parsed.hostname
    if is_platform_host(host):
        return
    try:
        normalize_custom_domain(host)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid origin") from None


def get_url(
    provider: str, *, origin: str, redirect: str, action: str, csrf: str, guard_hash: str | None = None
) -> schemas.OAuthURL:
    """``guard_hash`` is OPTIONAL: only the frontend's custom-domain apex
    bounce (``oauth-login.ts``) supplies one (``H = sha256_hex(G)`` of its
    host-only ``owt_xdomain_guard`` cookie). It is signed into the state
    verbatim (already a hash -- see ``OAuthService.encode_state``) and, when
    the eventual callback/link issues a cross-domain ticket, becomes that
    ticket's ``lg`` -- the binding ``sso_exchange``/``link_complete`` verify
    at redemption (Task 10R fix 1). A platform-host flow never supplies one.
    """
    _validate_origin(origin)
    if action not in _VALID_OAUTH_ACTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid OAuth action: {action}")
    try:
        url, state = OAuthService.generate_oauth_url(
            provider, origin=origin, redirect=redirect, action=action, csrf=csrf, guard_hash=guard_hash
        )
        return schemas.OAuthURL(provider=schemas.OAuthProvider(provider), url=url, state=state)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid provider: {provider}") from exc


def _verify_state_for(provider: str, state: str, *, expected_action: str) -> StatePayload:
    """Verify a signed ``state``, and that it was minted for THIS provider and action.

    ``OAuthService.verify_state`` only checks the HMAC + expiry (it has no
    notion of "the provider/action the caller expects"); the provider/action
    match here is what stops a state signed for e.g. a Discord *login* being
    replayed against a Twitch *link* callback.
    """
    try:
        payload = OAuthService.verify_state(state)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        ) from exc

    if payload.provider != provider or payload.action != expected_action:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")

    return payload


def _verify_csrf_binding(payload: StatePayload, csrf: str | None) -> None:
    """Bind the verified ``state`` to the browser that started the flow.

    ``payload.csrf`` is ``sha256(raw_cookie_token)``, computed at ``get_url``
    time (see ``OAuthService.encode_state``). ``csrf`` here is the RAW value
    of that same HttpOnly cookie, forwarded by the frontend on the
    callback/link RPC call. A state alone can be minted by anyone (they can
    call ``get_url`` for themselves) -- what an attacker running a login/
    account-linking CSRF attack CANNOT do is read the victim's HttpOnly
    cookie, so they cannot supply a ``csrf`` whose hash matches
    ``payload.csrf``.

    Fails CLOSED: a missing cookie (``csrf`` falsy) or a hash mismatch is
    always rejected with the same "invalid state" error the rest of this
    module uses -- never distinguished in the response, and the raw token is
    never logged (only compared, in constant time).
    """
    if not isinstance(csrf, str) or not csrf:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")

    csrf_hash = hashlib.sha256(csrf.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(csrf_hash, payload.csrf):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")


def _require_guard_hash_for_ticket(payload: StatePayload) -> str:
    """Fail-closed gate for cross-domain ticket ISSUANCE (Task 10R fix 1).

    Called by ``callback``/``link`` immediately before minting a cross-domain
    ticket (``sso_tickets.issue``/``pending_link_tickets.issue``). A verified
    state with no ``guard_hash`` means the flow never went through the
    custom-domain apex bounce that sets the browser-binding guard cookie --
    minting a ticket anyway would produce one with no ``lg``, which
    ``sso_exchange``/``link_complete`` could never verify against anything,
    defeating the whole binding. Raising here (same generic "invalid state"
    error the rest of this module uses) means an unbound ticket is NEVER
    issued, rather than issued-then-hopefully-rejected-later.
    """
    if not payload.guard_hash:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state")
    return payload.guard_hash


def _verify_guard_binding(guard: str | None, ticket_guard_hash: str | None) -> bool:
    """Bind a redeemed cross-domain ticket to the browser that started the flow.

    ``ticket_guard_hash`` is ``ticket.lg`` -- ``sha256_hex(G)``, stored on the
    ticket at issuance time from the verified state's ``guard_hash`` (see
    ``_require_guard_hash_for_ticket``). ``guard`` here is the RAW value of
    the caller's ``owt_xdomain_guard`` cookie, forwarded by the frontend's
    ticket-completion route. Mirrors ``_verify_csrf_binding`` one domain
    boundary further out: an attacker who ran their own flow and captured
    their own ticket cannot read the VICTIM's host-only guard cookie (no
    ``domain`` attribute -- it never leaves the browser that set it), so they
    cannot supply a ``guard`` whose hash matches ``ticket_guard_hash``.

    Fails CLOSED and returns a plain ``bool`` (never raises) so both callers
    -- ``sso_exchange`` (returns ``None``, no tokens) and ``link_complete``
    (raises the same "invalid ticket" error it already uses) -- can each
    apply their own existing fail-closed response shape. A missing ``guard``,
    a ticket with no ``lg`` at all, and a hash mismatch are all indistinguishable
    here; the raw guard value is only ever compared, in constant time, never
    logged.
    """
    if not isinstance(guard, str) or not guard:
        return False
    if not isinstance(ticket_guard_hash, str) or not ticket_guard_hash:
        return False
    guard_hash = hashlib.sha256(guard.encode("utf-8")).hexdigest()
    return hmac.compare_digest(guard_hash, ticket_guard_hash)


async def _consume_state_nonce(payload: StatePayload) -> None:
    """Enforce single-use of a verified state's nonce (replay protection).

    ``OAuthService.verify_state`` is pure/Redis-free on purpose (HMAC + exp
    only, so it stays unit-testable with no infra); this is the Redis-backed
    half that rejects a state being redeemed a second time. The nonce key's
    TTL mirrors the state's own expiry window, so it never outlives the state
    that carried it. If Redis is unreachable this fails OPEN (logs and lets
    the flow continue) rather than locking out every OAuth login -- the same
    posture ``init_redis()`` already takes for this service -- and the
    exp-bounded state format still caps the replay window at
    ``OAUTH_STATE_EXPIRE_MINUTES``.
    """
    ttl_seconds = max(settings.OAUTH_STATE_EXPIRE_MINUTES, 1) * 60
    key = f"{_STATE_NONCE_PREFIX}{payload.provider}:{payload.nonce}"
    try:
        redis = get_redis()
        consumed = await redis.set(key, "1", nx=True, ex=ttl_seconds)
    except (RuntimeError, RedisError) as exc:
        logger.warning(f"OAuth state nonce replay-check unavailable, continuing without it: {exc}")
        return

    if not consumed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state has already been used")


async def callback(
    session: AsyncSession,
    provider: str,
    code: str,
    state: str,
    user_agent: str | None,
    ip_address: str | None,
    csrf: str | None,
) -> schemas.OAuthCallbackResult:
    payload = _verify_state_for(provider, state, expected_action="login")
    _verify_csrf_binding(payload, csrf)
    await _consume_state_nonce(payload)

    auth_user, _ = await OAuthService.handle_callback(session, provider, code)

    if not auth_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    session_id, session_started_at = AuthService.create_session_metadata()
    access_token = AuthService.create_access_token(
        data={
            "sub": str(auth_user.id),
            "email": auth_user.email,
            "username": auth_user.username,
            "is_superuser": auth_user.is_superuser,
            "sid": str(session_id),
        }
    )
    refresh_token = AuthService.create_refresh_token()
    await AuthService.create_refresh_token_db(
        session,
        auth_user.id,
        refresh_token,
        None,
        session_id=session_id,
        session_started_at=session_started_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    # The platform apex / a `.owt` subdomain can read a cookie set by this
    # same callback (Domain=.owt in production); a custom domain cannot --
    # it's a different registrable domain. Hand it a one-time ticket instead
    # of the raw tokens; the custom domain's own frontend route redeems it
    # via rpc.identity.sso_exchange and sets host-only cookies itself.
    origin_host = urlparse(payload.origin).hostname
    if origin_host and not is_platform_host(origin_host):
        guard_hash = _require_guard_hash_for_ticket(payload)
        ticket = await sso_tickets.issue(access_token, refresh_token, payload.redirect, guard_hash=guard_hash)
        return schemas.OAuthCallbackResult(
            mode="ticket",
            ticket=ticket,
            origin=payload.origin,
            redirect=payload.redirect,
        )

    return schemas.OAuthCallbackResult(
        mode="cookie",
        access_token=access_token,
        refresh_token=refresh_token,
        origin=payload.origin,
        redirect=payload.redirect,
        action=payload.action,
    )


async def link(
    session: AsyncSession,
    user: models.AuthUser | None,
    provider: str,
    code: str,
    state: str,
    csrf: str | None,
) -> schemas.OAuthLinkResult:
    """Attach a provider identity to a site account (Task 10R re-architecture).

    State HMAC + csrf-binding + state-nonce single-use are verified FIRST and
    are completely unaffected by ``user``/the branch below (SECURITY
    INVARIANT #5) -- exactly as before this task.

    ``user`` is the LIVE apex/``.owt``-subdomain session the RPC layer
    resolved from a bearer access token, if one was presented (it may be
    ``None`` -- unlike every other authenticated RPC method, a missing bearer
    is not rejected before reaching here; see ``serve.py``'s
    ``rpc_oauth_link``). What happens next depends ONLY on the signed
    state's ``origin`` -- never on anything the caller supplied about who
    they are:

    - platform apex / a ``.owt`` subdomain: unchanged existing behavior --
      link the provider identity straight onto ``user``. If ``user`` is
      ``None`` (no bearer, or an invalid one), this is exactly the same
      "Not authenticated" signal callers got before this task.
    - a workspace custom domain: this response IS the fixed apex callback,
      which never shares a cookie with that domain (see module docstring),
      so ``user`` -- even if present -- is NOT the custom domain's live
      session and must never be used to link anything here (SECURITY
      INVARIANT #1). Instead, mint a single-use ticket carrying ONLY the
      just-exchanged PROVIDER identity (SECURITY INVARIANT #2); the custom
      domain's own frontend route resolves the actual linked-to user later,
      from ITS OWN live session (``link_complete``).

    Task 10R fix 1: a custom-domain ticket is only ever issued when the
    verified state carries a ``guard_hash`` (``_require_guard_hash_for_ticket``,
    fail closed) -- see the module docstring.
    """
    payload = _verify_state_for(provider, state, expected_action="link")
    _verify_csrf_binding(payload, csrf)
    await _consume_state_nonce(payload)

    provider_impl = OAuthService.get_provider(provider)
    token_data = await provider_impl.exchange_code(code)
    oauth_user_info = await provider_impl.get_user_info(token_data["access_token"])

    origin_host = urlparse(payload.origin).hostname
    if origin_host and not is_platform_host(origin_host):
        guard_hash = _require_guard_hash_for_ticket(payload)
        ticket = await pending_link_tickets.issue(oauth_user_info, token_data, guard_hash=guard_hash)
        return schemas.OAuthLinkResult(
            mode="link_ticket",
            ticket=ticket,
            origin=payload.origin,
            redirect=payload.redirect,
            action=payload.action,
        )

    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    await OAuthService.link_oauth_to_existing_user(session, user, oauth_user_info, token_data)
    return schemas.OAuthLinkResult(
        mode="linked",
        message=f"{provider.title()} account linked successfully",
        provider=provider,
        username=oauth_user_info.username,
        origin=payload.origin,
        redirect=payload.redirect,
        action=payload.action,
    )


async def sso_exchange(guard: str | None, ticket: str) -> dict | None:
    """Redeem a one-time SSO ticket, guard-bound (Task 10R fix 1).

    ``ticket`` is redeemed via ``sso_tickets.redeem`` (atomic GETDEL, single
    use) FIRST, exactly as before this fix; ``guard`` -- the RAW value of the
    caller's ``owt_xdomain_guard`` cookie -- is then checked against the
    redeemed payload's ``lg`` via ``_verify_guard_binding``. The ticket is
    already burned by the time that check runs, so a failed guard check can
    never be retried against the same ticket either way.

    Fails CLOSED: returns ``None`` (no tokens) for an invalid/expired/
    already-redeemed ticket, a missing ``guard``, a ticket minted with no
    ``lg`` at all, or a hash mismatch -- every one of those is indistinguishable
    from here, mirroring ``sso_tickets.redeem``'s own single generic failure
    shape. Called by ``serve.py``'s ``rpc_sso_exchange`` (public RPC, no
    bearer -- the ticket + guard pair together are the credential).
    """
    payload = await sso_tickets.redeem(ticket)
    if payload is None:
        return None
    if not _verify_guard_binding(guard, payload.get("lg")):
        return None
    return {"access_token": payload.get("access_token"), "refresh_token": payload.get("refresh_token")}


async def link_complete(session: AsyncSession, user: models.AuthUser, ticket: str, guard: str | None) -> dict:
    """Redeem a pending-link ticket and attach its PROVIDER identity to the
    BEARER-authenticated caller (step 6 of the Task 10R end-ticket flow).

    ``user`` is resolved by the RPC layer (``serve.py``'s ``_with_active_user``,
    same as ``unlink``/``connections``) from the access token presented on
    THIS call -- i.e. the live session on whichever host this RPC method was
    invoked for (the custom domain's own frontend route, never the apex).
    That bearer user IS the linked-to site account; nothing here reads a
    user/account identifier out of ``ticket`` or anywhere else, because the
    ticket never carries one (SECURITY INVARIANTS #1, #2, #4).

    Task 10R fix 1: ``guard`` -- the RAW value of the caller's
    ``owt_xdomain_guard`` cookie -- must additionally match the redeemed
    ticket's ``lg`` (``_verify_guard_binding``), fail closed, EVEN THOUGH the
    caller already presented a valid bearer. Without this, a valid bearer
    alone would let a victim's own browser complete an attacker's link
    ticket (reverse CSRF / account takeover via linking) -- the whole point
    of this fix. The ticket is already burned (single-use redeem, above) by
    the time this check runs.
    """
    payload = await pending_link_tickets.redeem(ticket)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link ticket")

    if not _verify_guard_binding(guard, payload.get("lg")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link ticket")

    try:
        oauth_user_info = schemas.OAuthUserInfo.model_validate(payload["oauth_info"])
        token_data = payload["token_data"]
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link ticket") from exc

    await OAuthService.link_oauth_to_existing_user(session, user, oauth_user_info, token_data)
    return {
        "message": f"{oauth_user_info.provider.value.title()} account linked successfully",
        "provider": oauth_user_info.provider.value,
        "username": oauth_user_info.username,
    }


async def connections(session: AsyncSession, user: models.AuthUser) -> list[schemas.OAuthUserInfo]:
    result = await session.execute(select(OAuthConnection).where(OAuthConnection.auth_user_id == user.id))
    return [
        schemas.OAuthUserInfo(
            provider=schemas.OAuthProvider(conn.provider),
            provider_user_id=conn.provider_user_id,
            email=conn.email,
            username=conn.username,
            display_name=conn.display_name,
            avatar_url=conn.avatar_url,
            raw_data=conn.provider_data or {},
        )
        for conn in result.scalars().all()
    ]


async def unlink(
    session: AsyncSession,
    user: models.AuthUser,
    provider: str,
    provider_user_id: str | None = None,
) -> None:
    """Unlink OAuth connection(s) for a provider.

    When ``provider_user_id`` is given, unlinks only that specific connection
    (a user may have several of the same provider); otherwise unlinks every
    connection for the provider. Drops the verified mark from the matching
    social account(s); the account row itself is kept (re-verify by re-linking).
    """
    if not user.hashed_password:
        result = await session.execute(select(OAuthConnection).where(OAuthConnection.auth_user_id == user.id))
        if len(result.scalars().all()) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink last OAuth provider. Set a password first.",
            )
    del_query = delete(OAuthConnection).where(
        OAuthConnection.auth_user_id == user.id, OAuthConnection.provider == provider
    )
    if provider_user_id is not None:
        del_query = del_query.where(OAuthConnection.provider_user_id == provider_user_id)
    result = await session.execute(del_query)
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{provider.title()} account not linked")

    provider_social = OAUTH_TO_SOCIAL.get(provider)
    if provider_social is not None:
        player = await session.scalar(select(models.User).where(models.User.auth_user_id == user.id))
        if player is not None:
            unverify = update(SocialAccount).where(
                SocialAccount.user_id == player.id,
                SocialAccount.provider == provider_social,
                SocialAccount.is_verified.is_(True),
            )
            if provider_user_id is not None:
                unverify = unverify.where(SocialAccount.provider_user_id == provider_user_id)
            await session.execute(unverify.values(is_verified=False, provider_user_id=None))

    await session.commit()
