"""RPC-callable service-to-service token flows.

Faithful ports of auth-service's /service routes: issue (client-credentials),
validate, and RBAC-cache invalidation. Pure compute (no DB); HMAC + JWT only.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, status

from src import schemas
from src.core.config import settings
from src.services.auth_service import AuthService
from src.services.session_cache import invalidate_rbac

_invalid_service_token = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid service token",
    headers={"WWW-Authenticate": "Bearer"},
)


def issue_service_token(client_id: str, client_secret: str) -> schemas.ServiceToken:
    expected_secret = settings.SERVICE_CLIENTS.get(client_id)
    if not expected_secret or not hmac.compare_digest(client_secret, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scopes = settings.SERVICE_SCOPES.get(client_id, [])
    token = AuthService.create_service_token(
        data={
            "sub": client_id,
            "scopes": scopes,
            "iss": settings.SERVICE_TOKEN_ISSUER,
            "aud": settings.SERVICE_TOKEN_AUDIENCE,
        }
    )
    return schemas.ServiceToken(
        access_token=token,
        expires_in=settings.SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        scopes=scopes,
    )


def _decode_service_payload(token: str) -> dict:
    payload = AuthService.decode_token(token)  # raises 401 on JWT error
    if payload.get("type") != "service":
        raise _invalid_service_token
    if payload.get("iss") != settings.SERVICE_TOKEN_ISSUER or payload.get("aud") != settings.SERVICE_TOKEN_AUDIENCE:
        raise _invalid_service_token
    return payload


def validate_service_token(token: str) -> schemas.ServiceTokenPayload:
    payload = _decode_service_payload(token)
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


async def invalidate_session(token: str, user_id: int) -> None:
    _decode_service_payload(token)  # requires a valid service token
    await invalidate_rbac(user_id)
