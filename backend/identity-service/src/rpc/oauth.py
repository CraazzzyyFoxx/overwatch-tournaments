"""OAuth login/link flows, including the custom-domain ticket handoff.

Transport only: parse the RPC payload, resolve the caller when the method needs
one, hand off to a service object, serialise the result. Every authorization
decision, query and error message belongs to ``src/services/**``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import Channel
from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from src.schemas.rpc import rpc_error, rpc_ok
from src.services.oauth import oauth
from src.services.token_validation import token_validation

from . import _common as c

__all__ = ("register",)


# Isolated QoS: these three flows block on an external provider (Discord/Twitch/
# Battle.net token + userinfo exchanges), which is why the gateway had to raise
# its identity RPC timeout to 20s for them. On the DEFAULT channel a handful of
# slow provider calls occupy the process-wide RPC_PREFETCH_COUNT slots that
# ``rpc.identity.validate_token`` -- the hot path every authenticated request on
# the platform goes through -- needs, and the gateway then sheds token
# validations while identity-svc is merely waiting on someone else's HTTP
# (Sentry OWT-TOURNAMENTS-20B / 2A9). Their own channel bounds that to 8 and
# leaves the default channel's slots to the cheap, Redis-cached RPCs -- mirrors
# balancer ``_JOBS_CHANNEL`` and tournament ``reg_pub_list``.
_PROVIDER_CHANNEL = Channel(prefetch_count=8)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.identity.oauth_providers")
    async def _oauth_providers(data: dict, msg: RabbitMessage) -> dict:
        return rpc_ok([provider.model_dump(mode="json") for provider in oauth.list_providers()])

    @broker.subscriber("rpc.identity.oauth_url")
    async def _oauth_url(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}
        provider = data.get("provider")
        if not provider or not isinstance(provider, str):
            return rpc_error("bad_request", "provider is required")
        origin, redirect, action = data.get("origin"), data.get("redirect"), data.get("action")
        if not origin or not isinstance(origin, str):
            return rpc_error("bad_request", "origin is required")
        if not isinstance(redirect, str) or not redirect:
            redirect = "/"
        if not action or not isinstance(action, str):
            return rpc_error("bad_request", "action is required")
        csrf = data.get("csrf")
        if not csrf or not isinstance(csrf, str):
            return rpc_error("bad_request", "csrf is required")
        # Optional (Task 10R fix 1): only the frontend's custom-domain apex bounce
        # supplies this (see oauth-login.ts). Anything not a non-empty string is
        # treated as absent -- the state carries it only when present.
        guard_hash = data.get("guard_hash")
        if not isinstance(guard_hash, str) or not guard_hash:
            guard_hash = None

        async def run() -> dict:
            result = oauth.authorization_url(
                provider, origin=origin, redirect=redirect, action=action, csrf=csrf, guard_hash=guard_hash
            )
            return result.model_dump(mode="json")

        return await c.envelope(logger, "oauth_url", run)

    @broker.subscriber("rpc.identity.oauth_callback", channel=_PROVIDER_CHANNEL)
    async def _oauth_callback(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}
        provider, code, state = data.get("provider"), data.get("code"), data.get("state")
        if not (provider and code and state):
            return rpc_error("unprocessable", "provider, code and state are required")

        async def run(session: AsyncSession) -> dict:
            result = await oauth.callback(
                session,
                provider,
                code,
                state,
                data.get("user_agent"),
                data.get("ip_address"),
                data.get("csrf"),
            )
            return result.model_dump(mode="json")

        return await c.envelope_session(
            logger, "oauth_callback", run, failure=f"OAuth authentication failed for {provider}"
        )

    @broker.subscriber("rpc.identity.sso_exchange")
    async def _sso_exchange(data: dict, msg: RabbitMessage) -> dict:
        """Redeem a one-time SSO ticket (custom-domain OAuth callback handoff).

        Called by the custom domain's own frontend route -- never by the apex --
        after the callback returned `mode="ticket"`. The ticket is single-use
        (Redis GETDEL); a missing, expired, already-redeemed, or unknown ticket all
        look identical from here, as does a `guard` cookie that fails the
        browser-binding check (Task 10R fix 1).
        """
        data = data or {}
        ticket = data.get("ticket")
        if not ticket or not isinstance(ticket, str):
            return rpc_error("bad_request", "ticket is required")

        result = await oauth.sso_exchange(data.get("guard"), ticket)
        if result is None:
            return rpc_error("bad_request", "invalid or expired ticket")
        return rpc_ok(result)

    @broker.subscriber("rpc.identity.oauth_link", channel=_PROVIDER_CHANNEL)
    async def _oauth_link(data: dict, msg: RabbitMessage) -> dict:
        """Custom-domain-aware account-link callback (Task 10R re-architecture).

        Unlike every OTHER authenticated RPC method here, a missing bearer is NOT
        rejected up front -- `oauth.link` decides whether one is required, branching
        on the signed OAuth state's origin: a platform-host link still requires a
        resolvable user, but a custom-domain link never does; it can only ever mint
        a single-use provider-identity ticket for a LIVE session on the custom
        domain itself to redeem later (`rpc.identity.link_complete`).

        A *present but invalid* access_token is treated the same as a missing one
        (best-effort resolution, mirroring the gateway's own fail-safe-to-anonymous
        posture for this route) so a stale platform cookie can never block an
        otherwise-valid custom-domain ticket issuance.
        """
        data = data or {}
        provider, code, state = data.get("provider"), data.get("code"), data.get("state")
        if not (provider and code and state):
            return rpc_error("unprocessable", "provider, code and state are required")
        access_token = data.get("access_token")

        async def run(session: AsyncSession) -> dict:
            user = None
            if access_token:
                try:
                    user = await token_validation.resolve_active_user(session, access_token)
                except HTTPException:
                    user = None
            result = await oauth.link(session, user, provider, code, state, data.get("csrf"))
            return result.model_dump(mode="json")

        return await c.envelope_session(logger, "oauth_link", run)

    @broker.subscriber("rpc.identity.link_complete")
    async def _link_complete(data: dict, msg: RabbitMessage) -> dict:
        """Redeem a pending-link ticket and attach its PROVIDER identity to the
        bearer-authenticated caller (step 6 of the Task 10R end-ticket flow).

        A bearer is mandatory here (SECURITY INVARIANT #4): this is the step that
        resolves the linked-to site account, and that resolution must come from
        nothing but the live session presented on THIS call. `guard` is the raw
        `owt_xdomain_guard` cookie; the redemption fails closed on a mismatch even
        though the bearer is valid.
        """
        data = data or {}
        ticket = data.get("ticket")
        guard = data.get("guard")

        async def op(session: AsyncSession, user: Any) -> dict:
            if not ticket or not isinstance(ticket, str):
                raise HTTPException(status_code=422, detail="ticket is required")
            return await oauth.link_complete(session, user, ticket, guard)

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.oauth_connections")
    async def _oauth_connections(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> list[dict]:
            conns = await oauth.connections_for(session, user)
            return [conn.model_dump(mode="json") for conn in conns]

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.oauth_unlink")
    async def _oauth_unlink(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}
        provider = data.get("provider")
        # Optional: target one specific connection when several of the same provider
        # are linked; omitted = unlink all connections for the provider.
        provider_user_id = data.get("provider_user_id")

        async def op(session: AsyncSession, user: Any) -> None:
            if not provider:
                raise HTTPException(status_code=400, detail="provider is required")
            await oauth.unlink(session, user, provider, provider_user_id=provider_user_id)

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.oauth_discord_guilds", channel=_PROVIDER_CHANNEL)
    async def _oauth_discord_guilds(data: dict, msg: RabbitMessage) -> dict:
        """Guilds the given ``auth_user_id`` administers on Discord.

        Internal, service-to-service only (no gateway route) -- called by
        ``rpc.app.workspaces.discord_guild_verify`` to prove ownership before a
        workspace can claim a guild id (workspace self-service design, §4.1).
        Trusted broker traffic, so the caller passes ``auth_user_id`` directly
        rather than a bearer token, same trust boundary as every other
        internal-only subject in this stack.
        """
        data = data or {}
        auth_user_id = data.get("auth_user_id")

        async def op(session: AsyncSession) -> dict:
            if not auth_user_id:
                raise HTTPException(status_code=422, detail="auth_user_id is required")
            guilds = await oauth.discord_guilds(session, auth_user_id=int(auth_user_id))
            return {"guilds": guilds}

        return await c.envelope_session(logger, "oauth_discord_guilds", op)
