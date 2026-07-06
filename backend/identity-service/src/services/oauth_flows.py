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
    try:
        hostname = urlparse(origin).hostname
    except ValueError:
        hostname = None
    if not hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid origin")
    if is_platform_host(hostname):
        return
    try:
        normalize_custom_domain(hostname)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid origin") from None


def get_url(provider: str, *, origin: str, redirect: str, action: str, csrf: str) -> schemas.OAuthURL:
    _validate_origin(origin)
    if action not in _VALID_OAUTH_ACTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid OAuth action: {action}")
    try:
        url, state = OAuthService.generate_oauth_url(
            provider, origin=origin, redirect=redirect, action=action, csrf=csrf
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
    return schemas.OAuthCallbackResult(
        access_token=access_token,
        refresh_token=refresh_token,
        origin=payload.origin,
        redirect=payload.redirect,
        action=payload.action,
    )


async def link(
    session: AsyncSession, user: models.AuthUser, provider: str, code: str, state: str, csrf: str | None
) -> dict:
    payload = _verify_state_for(provider, state, expected_action="link")
    _verify_csrf_binding(payload, csrf)
    await _consume_state_nonce(payload)

    provider_impl = OAuthService.get_provider(provider)
    token_data = await provider_impl.exchange_code(code)
    oauth_user_info = await provider_impl.get_user_info(token_data["access_token"])
    await OAuthService.link_oauth_to_existing_user(session, user, oauth_user_info, token_data)
    return {
        "message": f"{provider.title()} account linked successfully",
        "provider": provider,
        "username": oauth_user_info.username,
        "origin": payload.origin,
        "redirect": payload.redirect,
        "action": payload.action,
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
