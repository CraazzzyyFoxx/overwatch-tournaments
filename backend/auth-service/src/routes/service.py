"""Service-to-service authentication routes (client credentials)."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from src import schemas
from src.core.config import settings
from src.services import auth_service
from src.services.session_cache import invalidate_rbac

router = APIRouter(prefix="/service", tags=["Service Auth"])
security = HTTPBearer()


@router.post("/token", response_model=schemas.ServiceToken)
async def issue_service_token(payload: schemas.ServiceTokenRequest) -> schemas.ServiceToken:
    """Issue a short-lived service token for internal calls."""
    expected_secret = settings.SERVICE_CLIENTS.get(payload.client_id)

    if not expected_secret or not hmac.compare_digest(payload.client_secret, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scopes = settings.SERVICE_SCOPES.get(payload.client_id, [])
    token = auth_service.AuthService.create_service_token(
        data={
            "sub": payload.client_id,
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


@router.post("/validate", response_model=schemas.ServiceTokenPayload)
async def validate_service_token(
    token: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> schemas.ServiceTokenPayload:
    """Validate service token and return its payload."""
    payload = auth_service.AuthService.decode_token(token.credentials)

    if payload.get("type") != "service":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("iss") != settings.SERVICE_TOKEN_ISSUER or payload.get("aud") != settings.SERVICE_TOKEN_AUDIENCE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

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


def _verify_service_token(token: HTTPAuthorizationCredentials) -> dict:
    """Decode and verify a service token, raising 401 on failure."""
    payload = auth_service.AuthService.decode_token(token.credentials)

    if payload.get("type") != "service":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("iss") != settings.SERVICE_TOKEN_ISSUER or payload.get("aud") != settings.SERVICE_TOKEN_AUDIENCE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


@router.post("/invalidate-session/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_user_session(
    user_id: int,
    token: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> None:
    """
    Invalidate the RBAC cache for a specific user.
    Called by other services when they need to force-refresh a user's permissions.
    Requires a valid service token.
    """
    _verify_service_token(token)
    await invalidate_rbac(user_id)
    logger.info(f"Session invalidated for user {user_id} via internal API")
