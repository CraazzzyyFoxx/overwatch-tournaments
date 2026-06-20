"""Token validation as a service function (RPC-callable, no FastAPI request).

Reuses the exact validation logic from the HTTP route so behaviour stays
byte-for-byte identical with auth-service: API-key path or JWT decode + RBAC.
1B will move these helpers into a dedicated service when login/refresh need
them too; for now we reuse the route's implementation to guarantee parity.
"""

from __future__ import annotations

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.services import api_key_service
from src.services.auth_token_helpers import _build_access_token_payload, _resolve_access_token_user


async def validate_token(session: AsyncSession, raw_token: str) -> schemas.TokenPayload:
    """Validate a JWT access token or workspace-scoped API key, returning RBAC.

    Raises HTTPException (401/403/...) on invalid credentials, matching the
    auth-service /validate route exactly.
    """
    if raw_token.startswith(f"{api_key_service.API_KEY_PREFIX}_"):
        api_key_payload = await api_key_service.validate_api_key(session, raw_token)
        if api_key_payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return api_key_payload

    current_user = await _resolve_access_token_user(session, raw_token)
    return await _build_access_token_payload(session, current_user)
