"""Credential validation: the gateway's per-request entry point.

Three resolvers, and the differences between them are load-bearing:

* ``validate`` answers the gateway's token-introspection call and collapses every
  "not authenticated" outcome — including an inactive account — into 401.
* ``resolve_active_user`` backs the authenticated RPC operations and reports an
  inactive account as 403, because there the credential itself was valid. It
  accepts a JWT access token and nothing else, and that is a security boundary:
  everything it guards mutates a session, a credential or RBAC, so an API key
  must never reach it — a key that could mint keys or extend its own life would
  not be workspace-scoped in any meaningful sense.
* ``resolve_active_principal`` accepts either credential, for the read-only
  introspection an API key is legitimately allowed to perform ("who am I",
  "which key am I"). Opt in per subscriber, never by default.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from shared.repository import OAuthConnectionRepository
from src import schemas
from src.services.api_keys import ApiKeyService, api_keys
from src.services.auth_users import AuthUserService, auth_users
from src.services.security import TokenCodec, token_codec
from src.services.session_cache import SessionCache, session_cache
from src.services.token_payload import TokenPayloadBuilder, token_payloads

__all__ = ["TokenValidationService", "token_validation"]


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _not_linked() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discord account is not linked")


def _stamp_rbac(user: models.AuthUser, payload: schemas.TokenPayload) -> None:
    """Attach ``payload``'s RBAC to ``user`` as the model's instance cache.

    Mandatory, not an optimisation. Both resolvers below return a row loaded
    with ``noload(AuthUser.roles)`` -- ``get_identity`` for a bearer token, and
    the API-key path -- because RBAC comes from the payload, never the row.
    ``noload`` yields an EMPTY collection rather than raising, so without this
    every ``has_permission`` / ``has_workspace_permission`` on such a user
    silently answers False; only ``is_superuser`` (a column on the row) survives.
    """
    user.set_rbac_cache(
        role_names=payload.roles,
        permissions=payload.permissions,
        workspaces=[{"workspace_id": ws.workspace_id, "slug": ws.slug} for ws in payload.workspaces],
        workspace_rbac={
            ws.workspace_id: {"roles": ws.rbac_roles, "permissions": ws.rbac_permissions} for ws in payload.workspaces
        },
        denies=payload.denies,
    )


class TokenValidationService:
    """Resolves a raw credential (JWT access token or API key) to RBAC."""

    def __init__(
        self,
        *,
        codec: TokenCodec = token_codec,
        cache: SessionCache = session_cache,
        users: AuthUserService = auth_users,
        payloads: TokenPayloadBuilder = token_payloads,
        keys: ApiKeyService = api_keys,
        connections: OAuthConnectionRepository = OAuthConnectionRepository(),
    ) -> None:
        self.codec = codec
        self.cache = cache
        self.users = users
        self.payloads = payloads
        self.keys = keys
        self.connections = connections

    async def validate(self, session: AsyncSession, raw_token: str) -> schemas.TokenPayload:
        """Validate a JWT access token or workspace-scoped API key, returning RBAC.

        Raises 401 on any invalid credential — including a decodable token for a
        deactivated account, which on this path is indistinguishable from a bad
        token by design (the gateway has no user to report 403 about).

        A full RBAC cache hit answers from Redis alone (one round trip, zero SQL):
        the entry carries the account's ``is_active`` and is dropped with every
        change to it. A miss loads the identity-only row -- after the generation
        that fences the fill was read -- and fills the entry.
        """
        if self.keys.is_api_key(raw_token):
            api_key_payload = await self.keys.validate(session, raw_token)
            if api_key_payload is None:
                raise _credentials_error()
            return api_key_payload

        user_id, _session_id, cached, generation = await self._resolve_bearer(raw_token)
        resolved = await self.payloads.resolve(
            session, user_id, self.users.get_identity, cached=cached, generation=generation
        )
        if resolved is None or not resolved[1]:
            raise _credentials_error()
        return resolved[0]

    async def discord_identity(self, session: AsyncSession, discord_user_id: str) -> schemas.TokenPayload:
        """RBAC for the account a Discord user id is linked to, for the bot to act as.

        A button click on a notification card carries no bearer token: the OAuth
        link *is* the credential, so the Discord id the bot reports plus the
        connection row is the whole authentication. That only holds for trusted
        broker traffic, which is why the subject is internal-only with no gateway
        route, the same trust boundary as ``rpc.identity.oauth_discord_guilds``.

        Deliberately not cached on the caller's side: unlinking the account must
        stop working on the next click, not once some TTL happens to lapse.
        """
        connection = await self.connections.get_by_provider_subject(
            session, provider=SocialProvider.DISCORD, provider_user_id=discord_user_id
        )
        if connection is None:
            raise _not_linked()
        resolved = await self.payloads.resolve(session, connection.auth_user_id, self.users.get_identity)
        if resolved is None:
            # The link outlived the account row; indistinguishable from "never
            # linked" to the bot, and the same thing to tell the clicking user.
            raise _not_linked()
        payload, is_active = resolved
        if not is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
        return payload.model_copy(update={"credential_type": "discord"})

    async def resolve_active_user(self, session: AsyncSession, raw_token: str) -> models.AuthUser:
        """Resolve the authenticated, active user from a bearer access token.

        Stamps ``_current_session_id`` so session-scoped operations (logout,
        session list/revoke) can tell the caller's own session apart from the
        others without re-decoding the token.
        """
        user_id, session_id, cached, generation = await self._resolve_bearer(raw_token)
        # The ORM row, not the payload: handlers mutate it. Identity-only, so
        # the RBAC every caller then authorizes against has to be stamped from
        # ``build`` -- free on a full cache hit, a fill otherwise. Loaded after
        # ``_resolve_bearer`` read the generation that fences that fill.
        user = await self.users.get_identity(session, user_id)
        if user is None:
            raise _credentials_error()
        if session_id is not None:
            object.__setattr__(user, "_current_session_id", session_id)
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
        _stamp_rbac(user, await self.payloads.build(session, user, cached=cached, generation=generation))
        return user

    async def resolve_active_principal(
        self,
        session: AsyncSession,
        raw_token: str,
    ) -> tuple[models.AuthUser, schemas.TokenApiKeyInfo | None]:
        """Resolve the active principal behind a JWT access token *or* an API key.

        The second element identifies the key the caller presented (``None`` for a
        session), so a handler can answer questions about the credential itself
        without re-parsing or re-verifying it.
        """
        if not self.keys.is_api_key(raw_token):
            return await self.resolve_active_user(session, raw_token), None

        # One ``None`` for a bad secret, a revoked or expired key, a deactivated
        # owner, or an owner who lost workspace access — deliberately
        # indistinguishable, and reused rather than re-derived so this door can
        # never drift open wider than the gateway's own.
        payload = await self.keys.validate(session, raw_token)
        if payload is None:
            raise _credentials_error()

        # ``validate`` already rejected an inactive owner, so no second liveness
        # check here. Identity-only load: an API key's RBAC comes from the payload
        # above, never from the owner's ORM relationships.
        user = await self.users.get_identity(session, payload.sub)
        if user is None:
            raise _credentials_error()
        _stamp_rbac(user, payload)
        return user, payload.api_key

    async def _resolve_bearer(self, raw_token: str) -> tuple[int, str | None, dict[str, Any], str | None]:
        """Decode a bearer token and read its Redis state: ``(user id, sid, RBAC entry, generation)``.

        The entry is ``{}`` on a miss/outage and is returned rather than
        discarded, so ``build`` does not read it a second time on the same
        request; the generation, read before any account row is loaded, is what
        a fill on this request hands to ``set_rbac``.
        """
        credentials_exception = _credentials_error()
        # Narrow the catch to the decode only: a downstream 403/404
        # HTTPException must not be silently collapsed into a 401.
        try:
            payload = self.codec.decode(raw_token)
        except HTTPException:
            raise credentials_exception

        user_id_str = payload.get("sub")
        token_type = payload.get("type")
        session_id = payload.get("sid")
        if not user_id_str or token_type != "access":
            raise credentials_exception
        try:
            user_id = int(user_id_str)
        except (TypeError, ValueError):
            raise credentials_exception
        if not isinstance(session_id, str) or not session_id:
            session_id = None

        # A revoked session (logout / revoke / reuse-detection) blacklists its
        # sid; reject the still-unexpired access token that carries it. This is
        # the path the gateway hits on every request, so the check propagates
        # globally (bounded by the gateway's short token cache). Read together
        # with the RBAC entry: one round trip for both.
        cached, generation, revoked = await self.cache.token_state(user_id, session_id)
        if revoked:
            raise credentials_exception
        return user_id, session_id, cached or {}, generation


token_validation = TokenValidationService()
