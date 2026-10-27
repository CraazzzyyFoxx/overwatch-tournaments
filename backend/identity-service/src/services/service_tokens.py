"""Service-to-service token issue / validate / RBAC-cache invalidation.

Pure compute plus Redis: HMAC + JWT only, no database access. That constraint is
load-bearing for ``invalidate_rbac`` — see its docstring.
"""

from __future__ import annotations

import hmac
from typing import Any

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import schemas
from src.core.config import settings
from src.services.security import TokenCodec, token_codec
from src.services.session_cache import SessionCache, session_cache

__all__ = ("ServiceTokenService", "service_tokens")

# One shared instance: every rejection path must be indistinguishable to a
# machine client, so they all raise the identical exception object.
_invalid_service_token = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid service token",
    headers={"WWW-Authenticate": "Bearer"},
)

# The one scope ``invalidate_rbac`` demands (SERVICE_SCOPES in auth.env grants it per client).
INVALIDATE_SCOPE = "identity:invalidate"


class ServiceTokenService:
    def __init__(
        self,
        *,
        codec: TokenCodec = token_codec,
        cache: SessionCache = session_cache,
        config: Any = settings,
    ) -> None:
        self.codec = codec
        self.cache = cache
        self.config = config

    def issue(self, client_id: str, client_secret: str) -> schemas.ServiceToken:
        expected_secret = self.config.SERVICE_CLIENTS.get(client_id)
        if not expected_secret or not hmac.compare_digest(client_secret, expected_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid service credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scopes = self.config.SERVICE_SCOPES.get(client_id, [])
        token = self.codec.service_token(
            {
                "sub": client_id,
                "scopes": scopes,
                "iss": self.config.SERVICE_TOKEN_ISSUER,
                "aud": self.config.SERVICE_TOKEN_AUDIENCE,
            }
        )
        return schemas.ServiceToken(
            access_token=token,
            expires_in=self.config.SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            scopes=scopes,
        )

    def _decode(self, token: str) -> dict:
        payload = self.codec.decode(token)  # raises 401 on JWT error
        if payload.get("type") != "service":
            raise _invalid_service_token
        if (
            payload.get("iss") != self.config.SERVICE_TOKEN_ISSUER
            or payload.get("aud") != self.config.SERVICE_TOKEN_AUDIENCE
        ):
            raise _invalid_service_token
        return payload

    def validate(self, token: str) -> schemas.ServiceTokenPayload:
        payload = self._decode(token)
        scopes = payload.get("scopes")
        if not isinstance(scopes, list):
            scopes = []
        return schemas.ServiceTokenPayload(
            sub=str(payload.get("sub")),
            scopes=[str(s) for s in scopes],
            iss=str(payload.get("iss")) if payload.get("iss") is not None else None,
            aud=str(payload.get("aud")) if payload.get("aud") is not None else None,
            exp=payload.get("exp"),
        )

    async def invalidate_rbac(self, token: str, user_id: int) -> None:
        """Drop the cached RBAC for ``user_id``; tokens and sessions are untouched.

        The next request from that user re-resolves roles and permissions from the
        database instead of the cached Redis entry, so a grant or a deny applied
        out-of-band takes effect immediately rather than after ``RBAC_TTL``.

        **This does not end a session and does not revoke a token**, despite the
        ``/service/invalidate-session`` RPC name it serves. An access token stays
        valid until it expires; the mechanism that actually kills one is
        ``SessionCache.blacklist_session``, driven by the session service's revoke
        paths — all of which write to the database, which this module deliberately
        does not do (see the module docstring). The wire name is kept because
        ``/service/invalidate-session`` is an existing service-to-service contract
        and machine clients are configured outside this repository; renaming it
        would break callers we cannot see.
        """
        if INVALIDATE_SCOPE not in self.validate(token).scopes:  # validate() raises 401 on a bad token
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Service token lacks the {INVALIDATE_SCOPE} scope",
            )
        await self.cache.invalidate_rbac(user_id)


service_tokens = ServiceTokenService()
