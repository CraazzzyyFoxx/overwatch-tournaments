"""RPC-callable OAuth flows: authorization URL, callback, linking, unlinking.

OAuth ``state`` is a signed, self-contained payload (HMAC + short TTL) carrying
the originating host, the post-auth redirect and the intent, so the ONE fixed
apex callback registered with every provider can send the user back to the
tenant subdomain or custom domain that started the flow — with no shared
storage for the CSRF check itself. The one part that does need shared storage,
single-use nonce replay protection, is Redis-backed here
(:meth:`OAuthFlowService._consume_state_nonce`). Callbacks return the decoded
state fields; the frontend performs its own redirect back to ``origin``.

Two distinct CSRF defences run on top of that, one per domain boundary.

**1. The apex leg: ``csrf`` ↔ state.** A valid signature is not proof the
callback came from the browser that started the flow — anyone can mint a signed
state by calling :meth:`authorization_url` themselves (login / account-linking
CSRF). So the state embeds ``sha256(raw_csrf_cookie)``, and
``callback``/``link`` require the RAW value of that HttpOnly cookie back
(:meth:`_verify_csrf_binding`). An attacker cannot read the victim's HttpOnly
cookie; a missing or mismatched one is rejected exactly like an invalid state.

**2. The cross-domain leg: ``owt_xdomain_guard`` ↔ ticket.** The binding above
only covers apex start → apex callback. The cross-domain tickets minted for a
custom-domain origin are redeemed by a standalone GET route on that other
domain, where no apex cookie is readable. Without a second binding an attacker
could run their OWN flow with ``origin=<victim-domain>``, capture their OWN
ticket, and lure the victim into opening ``/auth/sso?ticket=`` or
``/auth/link/complete?ticket=`` — the victim's browser would redeem the
attacker's ticket (session fixation, or account takeover via linking). So the
frontend's custom-domain apex bounce sets a host-only ``owt_xdomain_guard``
cookie with raw value ``G`` and signs ``H = sha256_hex(G)`` into the state as
``guard_hash``; ``H`` is stored on the issued ticket and redemption requires
``G`` again (constant-time compare, inside ``TicketStore.redeem``). A host-only
cookie never leaves the browser that set it, so the victim cannot satisfy the
attacker's binding. Issuance is fail-closed too: a ticket-mode callback/link
whose verified state carries no ``guard_hash`` is an error, never an unbound
ticket (:meth:`_require_guard_hash_for_ticket`).
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import social_provider_for_oauth
from shared.repository import AuthUserRepository, OAuthConnectionRepository, SocialAccountRepository, UserRepository
from shared.tenancy.hostnames import is_platform_host, normalize_custom_domain
from src import schemas
from src.core.cache import _UNAVAILABLE, RedisStore
from src.core.config import Settings, settings
from src.services.auth import AuthenticationService, auth
from src.services.oauth_accounts import OAuthAccountService, oauth_accounts, open_token
from src.services.oauth_providers import OAuthProviderRegistry, OAuthTokenRejected, has_manage_guild, oauth_providers
from src.services.oauth_state import OAuthStateCodec, StatePayload, oauth_state
from src.services.tickets import LINK_TICKETS, SSO_TICKETS, TicketStore, guard_digest

# Every state/binding failure answers with the same text, so the response never
# tells an attacker which check failed.
_INVALID_STATE = "Invalid or expired OAuth state"
_INVALID_LINK_TICKET = "Invalid or expired link ticket"


def _discord_guild_icon_url(guild_id: object, icon: object) -> str | None:
    """CDN URL for a guild icon hash from ``GET /users/@me/guilds``.

    Discord stores the hash without a host; animated icons use the ``a_`` prefix
    and must be requested as ``.gif``. Missing/empty hashes mean no icon.
    """
    if not icon or not guild_id:
        return None
    digest = str(icon)
    ext = "gif" if digest.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/icons/{guild_id}/{digest}.{ext}"


class OAuthFlowService:
    """The RPC-facing OAuth flows; owns every policy decision in the module docstring."""

    # A signed ``state`` may only carry these: "login" starts/continues a
    # session, "link" attaches a provider to the CURRENT authenticated user.
    VALID_ACTIONS = frozenset({"login", "link"})

    def __init__(
        self,
        *,
        providers: OAuthProviderRegistry = oauth_providers,
        state: OAuthStateCodec = oauth_state,
        accounts: OAuthAccountService = oauth_accounts,
        authentication: AuthenticationService = auth,
        connections: OAuthConnectionRepository = OAuthConnectionRepository(),
        socials: SocialAccountRepository = SocialAccountRepository(),
        players: UserRepository = UserRepository(),
        users: AuthUserRepository = AuthUserRepository(),
        sso_tickets: TicketStore = SSO_TICKETS,
        link_tickets: TicketStore = LINK_TICKETS,
        config: Settings = settings,
    ) -> None:
        self.providers = providers
        self.state = state
        self.accounts = accounts
        self.authentication = authentication
        self.connections = connections
        self.socials = socials
        self.players = players
        self.users = users
        self.sso_tickets = sso_tickets
        self.link_tickets = link_tickets
        self.config = config
        # The nonce key never outlives the state that carried it.
        self.state_nonces = RedisStore("oauth:state-nonce:", ttl=state.ttl_seconds, purpose="OAuth state nonce")

    def list_providers(self) -> list[schemas.OAuthProviderAvailability]:
        return [schemas.OAuthProviderAvailability(provider=p) for p in self.providers.available()]

    def authorization_url(
        self, provider: str, *, origin: str, redirect: str, action: str, csrf: str, guard_hash: str | None = None
    ) -> schemas.OAuthURL:
        """Sign a ``state`` for the flow and return ``provider``'s authorization URL.

        ``guard_hash`` is OPTIONAL: only the frontend's custom-domain apex
        bounce supplies one (``H = sha256_hex(G)`` of its host-only
        ``owt_xdomain_guard`` cookie). It is signed into the state verbatim —
        already a hash — and becomes the ``lg`` of any cross-domain ticket the
        eventual callback/link issues. A platform-host flow never supplies one.

        ``redirect_uri`` stays ``OAUTH_REDIRECT`` — the ONE fixed apex callback
        registered with every provider — regardless of ``origin``; ``origin``
        travels inside the signed state instead.
        """
        self._validate_origin(origin)
        if action not in self.VALID_ACTIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid OAuth action: {action}")
        try:
            state = self.state.encode(
                origin=origin, redirect=redirect, action=action, provider=provider, csrf=csrf, guard_hash=guard_hash
            )
            code_verifier = self.state.code_verifier(self.state.verify(state))
            url = self.providers.get(provider).get_authorization_url(state, code_verifier)
            return schemas.OAuthURL(provider=schemas.OAuthProvider(provider), url=url, state=state)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid provider: {provider}"
            ) from exc

    async def callback(
        self,
        session: AsyncSession,
        provider: str,
        code: str,
        state: str,
        user_agent: str | None,
        ip_address: str | None,
        csrf: str | None,
    ) -> schemas.OAuthCallbackResult:
        payload = self._verify_state_for(provider, state, expected_action="login")
        self._verify_csrf_binding(payload, csrf)
        await self._consume_state_nonce(payload)

        auth_user, _ = await self.accounts.handle_callback(
            session, provider, code, state=state, code_verifier=self.state.code_verifier(payload)
        )

        if not auth_user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

        token = await self.authentication.issue_session(
            session, auth_user, user_agent=user_agent, ip_address=ip_address
        )

        # The platform apex / a `.owt` subdomain can read a cookie set by this
        # same callback (Domain=.owt in production); a custom domain cannot --
        # it's a different registrable domain. Hand it a one-time ticket
        # instead of the raw tokens; the custom domain's own frontend route
        # redeems it via rpc.identity.sso_exchange and sets host-only cookies.
        if self._is_custom_domain(payload):
            guard_hash = self._require_guard_hash_for_ticket(payload)
            ticket = await self.sso_tickets.issue(
                {
                    "access_token": token.access_token,
                    "refresh_token": token.refresh_token,
                    "redirect": payload.redirect,
                },
                guard_hash=guard_hash,
            )
            return schemas.OAuthCallbackResult(
                mode="ticket",
                ticket=ticket,
                origin=payload.origin,
                redirect=payload.redirect,
            )

        return schemas.OAuthCallbackResult(
            mode="cookie",
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            origin=payload.origin,
            redirect=payload.redirect,
            action=payload.action,
        )

    async def link(
        self,
        session: AsyncSession,
        user: models.AuthUser | None,
        provider: str,
        code: str,
        state: str,
        csrf: str | None,
    ) -> schemas.OAuthLinkResult:
        """Attach a provider identity to a site account.

        State HMAC + csrf binding + nonce single-use are verified FIRST and are
        completely unaffected by ``user`` or the branch below.

        ``user`` is the LIVE apex/``.owt``-subdomain session the RPC layer
        resolved from a bearer access token, if one was presented — it may be
        ``None``, since unlike every other authenticated RPC method a missing
        bearer is not rejected before reaching here. What happens next depends
        ONLY on the signed state's ``origin``, never on anything the caller
        supplied about who they are:

        - platform apex / a ``.owt`` subdomain: link the provider identity
          straight onto ``user``. ``user is None`` is the "Not authenticated"
          signal.
        - a workspace custom domain: this response IS the fixed apex callback,
          which never shares a cookie with that domain, so ``user`` — even if
          present — is NOT the custom domain's live session and must never be
          linked here. Mint a single-use ticket carrying ONLY the just-exchanged
          PROVIDER identity, never a site user id; the custom domain's own
          frontend route resolves the linked-to account later, from ITS OWN live
          session (:meth:`link_complete`).
        """
        payload = self._verify_state_for(provider, state, expected_action="link")
        self._verify_csrf_binding(payload, csrf)
        await self._consume_state_nonce(payload)

        provider_impl = self.providers.get(provider)
        token_data = await provider_impl.exchange_code(
            code, state=state, code_verifier=self.state.code_verifier(payload)
        )
        oauth_user_info = await provider_impl.get_user_info(token_data["access_token"])

        if self._is_custom_domain(payload):
            guard_hash = self._require_guard_hash_for_ticket(payload)
            ticket = await self.link_tickets.issue(
                {"oauth_info": oauth_user_info.model_dump(mode="json"), "token_data": token_data},
                guard_hash=guard_hash,
            )
            return schemas.OAuthLinkResult(
                mode="link_ticket",
                ticket=ticket,
                origin=payload.origin,
                redirect=payload.redirect,
                action=payload.action,
            )

        if user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

        await self.accounts.link_to_user(session, user, oauth_user_info, token_data)
        return schemas.OAuthLinkResult(
            mode="linked",
            message=f"{provider.title()} account linked successfully",
            provider=provider,
            username=oauth_user_info.username,
            origin=payload.origin,
            redirect=payload.redirect,
            action=payload.action,
        )

    async def sso_exchange(self, guard: str | None, ticket: str) -> dict[str, Any] | None:
        """Redeem a one-time SSO ticket, guard-bound.

        ``guard`` is the RAW value of the caller's ``owt_xdomain_guard`` cookie.
        The ticket is burned (atomic GETDEL) BEFORE its binding is checked, so a
        failed guard check can never be retried against the same ticket.

        Fails CLOSED: an invalid, expired or already-redeemed ticket, a missing
        ``guard``, a ticket minted with no binding at all, and a mismatch are
        all indistinguishable — every one of them returns ``None``, no tokens.
        Called by ``rpc_sso_exchange`` (public RPC, no bearer: the ticket +
        guard pair together are the credential).
        """
        payload = await self.sso_tickets.redeem(ticket, guard)
        if payload is None:
            return None
        return {"access_token": payload.get("access_token"), "refresh_token": payload.get("refresh_token")}

    async def link_complete(
        self, session: AsyncSession, user: models.AuthUser, ticket: str, guard: str | None
    ) -> dict[str, Any]:
        """Redeem a pending-link ticket and attach its PROVIDER identity to the
        BEARER-authenticated caller.

        ``user`` is resolved by the RPC layer from the access token presented on
        THIS call — the live session on whichever host this method was invoked
        for (the custom domain's own frontend route, never the apex). That
        bearer user IS the linked-to account; nothing here reads an account
        identifier out of the ticket, because the ticket never carries one.

        ``guard`` must additionally match the ticket's binding, fail closed,
        EVEN THOUGH the caller already presented a valid bearer: without it a
        victim's own browser would happily complete an attacker's link ticket
        (reverse CSRF / account takeover via linking). The ticket is burned
        before that check runs, so a failure cannot be retried.
        """
        payload = await self.link_tickets.redeem(ticket, guard)
        if payload is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LINK_TICKET)

        try:
            oauth_user_info = schemas.OAuthUserInfo.model_validate(payload["oauth_info"])
            token_data = payload["token_data"]
        except (KeyError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_LINK_TICKET) from exc

        await self.accounts.link_to_user(session, user, oauth_user_info, token_data)
        return {
            "message": f"{oauth_user_info.provider.value.title()} account linked successfully",
            "provider": oauth_user_info.provider.value,
            "username": oauth_user_info.username,
        }

    async def connections_for(self, session: AsyncSession, user: models.AuthUser) -> list[schemas.OAuthUserInfo]:
        conns = await self.connections.list_by_user(session, user.id)
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
            for conn in conns
        ]

    async def discord_guilds(self, session: AsyncSession, *, auth_user_id: int) -> dict[str, Any]:
        """Guilds ``auth_user_id`` is in on Discord, live and uncached: ``{"guilds", "relink_required"}``.

        No DB write. Used by app-service to prove guild administration before a
        workspace can claim a Discord guild id, and to fill the guild picker.

        Asks with the first linked Discord account whose stored token is present
        and unexpired (a user may link several). None usable, or Discord refusing
        that token, answers ``relink_required`` with no guilds: no refresh-token
        exchange exists for any provider here, so only a re-link revives it.
        """
        now = datetime.now(UTC)
        conns = await self.connections.list_by_user_providers(session, auth_user_id=auth_user_id, providers=["discord"])
        conn = next(
            (c for c in conns if c.access_token and (c.token_expires_at is None or c.token_expires_at > now)),
            None,
        )
        access_token = open_token(conn.access_token) if conn is not None else None
        if access_token is None:
            return {"guilds": [], "relink_required": True}

        try:
            raw_guilds = await self.providers.get("discord").get_user_guilds(access_token)
        except OAuthTokenRejected:
            return {"guilds": [], "relink_required": True}
        guilds = [
            {
                "guild_id": str(g["id"]),
                "name": g.get("name"),
                "icon_url": _discord_guild_icon_url(g["id"], g.get("icon")),
                "owner": bool(g.get("owner", False)),
                "can_manage": bool(g.get("owner", False)) or has_manage_guild(str(g.get("permissions", "0"))),
            }
            for g in raw_guilds
        ]
        return {"guilds": guilds, "relink_required": False}

    async def unlink(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        provider: str,
        provider_user_id: str | None = None,
    ) -> None:
        """Unlink OAuth connection(s) for a provider.

        When ``provider_user_id`` is given, unlinks only that specific
        connection (a user may have several of the same provider); otherwise
        unlinks every connection for the provider. Drops the verified mark from
        the matching social account(s); the account row itself is kept
        (re-verify by re-linking).

        A social account can carry a verified mark with no surviving OAuth
        connection behind it — admin profile merges move verified rows between
        players without moving connections, and deleting an auth user cascades
        its connections while the player survives. Unlinking such a provider
        clears the now-unprovable mark and never trips the last-provider guard:
        nothing you can sign in with is being removed.

        The account row is locked before its connections are counted, so two
        concurrent unlinks of a passwordless account's last two providers
        serialize: the second sees the first's delete and is refused.
        """
        await self.users.lock(session, user.id)
        conns = await self.connections.list_by_user(session, user.id)
        targeted = [
            conn
            for conn in conns
            if conn.provider == provider and (provider_user_id is None or conn.provider_user_id == provider_user_id)
        ]
        if targeted and not user.hashed_password and len(targeted) == len(conns):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink last OAuth provider. Set a password first.",
            )

        if targeted:
            await self.connections.delete_for_provider(
                session, auth_user_id=user.id, provider=provider, provider_user_id=provider_user_id
            )

        unverified = 0
        provider_social = social_provider_for_oauth(provider)
        if provider_social is not None:
            player = await self.players.get_by_auth_user_id(session, user.id)
            if player is not None:
                unverified = await self.socials.unverify_for_player(
                    session, user_id=player.id, provider=provider_social, provider_user_id=provider_user_id
                )

        if not targeted and not unverified:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{provider.title()} account not linked")

        await session.commit()

    def _validate_origin(self, origin: str) -> None:
        """Reject an ``origin`` this service has no business signing into a state.

        ``origin`` is attacker-influenceable (it starts as whatever ``Host`` the
        browser hit) and gets echoed straight back out of ``callback``/``link``
        for the frontend to redirect to — so this is the open-redirect guard.

        identity-svc does not own the workspace database, so it cannot check
        ``origin`` against the set of verified custom domains. What it CAN do
        without a round trip is reject anything that isn't even a well-formed
        host:

        - the platform apex or a ``.owt`` subdomain: trusted outright.
        - any other syntactically-valid FQDN: accepted as a CANDIDATE custom
          domain. Required, because custom-domain login bounces its start to the
          apex and passes the real custom-domain origin as this parameter.
          Whether the host is an actual VERIFIED custom domain is enforced
          elsewhere: the frontend's allow-list and — decisively — the fact that
          the callback never hands a custom-domain origin raw tokens, only a
          one-time guard-bound ticket.
        - anything else (malformed URL, no host, ``javascript:``, empty string)
          is rejected here.
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

    @staticmethod
    def _is_custom_domain(payload: StatePayload) -> bool:
        """True when the signed ``origin`` is neither the platform apex nor a ``.owt`` subdomain."""
        origin_host = urlparse(payload.origin).hostname
        return bool(origin_host) and not is_platform_host(origin_host)

    def _verify_state_for(self, provider: str, state: str, *, expected_action: str) -> StatePayload:
        """Verify a signed ``state``, and that it was minted for THIS provider and action.

        The codec only checks the HMAC and expiry — it has no notion of the
        provider/action the caller expects. This match is what stops a state
        signed for e.g. a Discord *login* being replayed against a Twitch *link*.
        """
        try:
            payload = self.state.verify(state)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATE) from exc

        if payload.provider != provider or payload.action != expected_action:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATE)

        return payload

    @staticmethod
    def _verify_csrf_binding(payload: StatePayload, csrf: str | None) -> None:
        """Bind the verified ``state`` to the browser that started the flow.

        ``payload.csrf`` is ``sha256(raw_cookie_token)``, computed when the URL
        was minted; ``csrf`` is the RAW value of that same HttpOnly cookie,
        forwarded on the callback/link call. Anyone can mint a state; what an
        attacker running a login/account-linking CSRF cannot do is read the
        victim's HttpOnly cookie.

        Fails CLOSED: a missing cookie and a mismatch are both rejected with the
        same generic "invalid state" error, never distinguished in the response,
        and the raw token is only ever compared, in constant time, never logged.
        """
        if not isinstance(csrf, str) or not csrf:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATE)

        if not hmac.compare_digest(guard_digest(csrf), payload.csrf):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATE)

    @staticmethod
    def _require_guard_hash_for_ticket(payload: StatePayload) -> str:
        """Fail-closed gate for cross-domain ticket ISSUANCE.

        A verified state with no ``guard_hash`` means the flow never went
        through the custom-domain apex bounce that sets the browser-binding
        guard cookie. Minting anyway would produce a ticket with no ``lg``,
        which redemption could never verify against anything, defeating the
        whole binding. Raising here (same generic "invalid state" error) means
        an unbound ticket is NEVER issued, rather than
        issued-then-hopefully-rejected-later.
        """
        if not payload.guard_hash:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_STATE)
        return payload.guard_hash

    async def _consume_state_nonce(self, payload: StatePayload) -> None:
        """Enforce single-use of a verified state's nonce (replay protection).

        State verification is pure and infra-free on purpose (HMAC + exp only,
        so it stays unit-testable); this is the Redis-backed half that rejects a
        second redemption. It fails CLOSED: with Redis down a state cannot be
        proven unused, so the flow answers 503 ``unavailable`` (retry) before
        any code is exchanged, rather than accept a replay.
        """
        try:
            claimed = await self.state_nonces.claim(f"{payload.provider}:{payload.nonce}")
        except _UNAVAILABLE as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth sign-in is temporarily unavailable"
            ) from exc
        if not claimed:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state has already been used")


oauth = OAuthFlowService()
