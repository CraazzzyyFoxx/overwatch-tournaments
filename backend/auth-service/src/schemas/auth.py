import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

__all__ = (
    "UserRegister",
    "UserLogin",
    "Token",
    "TokenPayload",
    "SessionRead",
    "RefreshTokenRequest",
    "PasswordSetRequest",
    "ServiceTokenRequest",
    "ServiceToken",
    "ServiceTokenPayload",
    "TokenApiKeyInfo",
    "AuthLinkedPlayer",
    "AuthUser",
    "UserUpdate",
    "WorkspaceMembership",
)


class UserRegister(BaseModel):
    """Schema for user registration"""

    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Username can only contain letters, numbers, underscores and hyphens")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot be longer than 72 bytes")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    """Schema for user login"""

    email: EmailStr
    password: str = Field(..., max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot be longer than 72 bytes")
        return v


class Token(BaseModel):
    """Schema for token response"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class SessionRead(BaseModel):
    """Logical auth session visible to the current user."""

    session_id: str
    is_current: bool = False
    status: str
    login_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip_address: str | None = None


class WorkspaceMembership(BaseModel):
    """Schema for workspace membership info"""

    workspace_id: int
    slug: str
    role: str
    rbac_roles: list[str] = Field(default_factory=list)
    rbac_permissions: list[dict[str, str]] = Field(default_factory=list)


class TokenApiKeyInfo(BaseModel):
    """API key metadata returned by token validation for downstream services."""

    id: int
    public_id: str
    workspace_id: int
    scopes: list[str] = Field(default_factory=list)
    limits: dict = Field(default_factory=dict)
    config_policy: dict = Field(default_factory=dict)


class TokenPayload(BaseModel):
    """Schema for JWT token payload"""

    sub: int  # user_id
    email: str
    username: str
    is_superuser: bool = False
    roles: list[str] = Field(default_factory=list)  # List of role names
    permissions: list[dict[str, str]] = Field(default_factory=list)  # List of {resource, action} dicts
    workspaces: list[WorkspaceMembership] = Field(default_factory=list)
    credential_type: Literal["access_token", "api_key"] = "access_token"
    api_key: TokenApiKeyInfo | None = None
    exp: int | None = None


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request"""

    refresh_token: str


class PasswordSetRequest(BaseModel):
    """Schema for setting/changing password."""

    new_password: str = Field(..., min_length=8, max_length=100)
    current_password: str | None = Field(default=None, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot be longer than 72 bytes")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("current_password")
    @classmethod
    def validate_current_password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot be longer than 72 bytes")
        return v


class AuthUserWorkspace(BaseModel):
    """Workspace RBAC info for authenticated user response."""

    workspace_id: int
    slug: str
    role: str
    rbac_roles: list[str] = Field(default_factory=list)
    rbac_permissions: list[str] = Field(default_factory=list)


class AuthLinkedPlayer(BaseModel):
    """Analytics player linked to the authenticated user."""

    player_id: int
    player_name: str
    is_primary: bool
    linked_at: str


class AuthUser(BaseModel):
    """Schema for authenticated user response"""

    id: int
    email: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    is_superuser: bool
    is_verified: bool
    roles: list[str] = Field(default_factory=list)  # List of role names
    permissions: list[str] = Field(default_factory=list)  # List of "resource.action" strings
    workspaces: list[AuthUserWorkspace] = Field(default_factory=list)
    linked_players: list[AuthLinkedPlayer] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("roles", mode="before")
    @classmethod
    def normalize_roles(cls, v):
        # When using from_attributes=True, SQLAlchemy relationships come through
        # as lists of ORM objects. Convert Role objects -> role.name.
        if v is None:
            return []
        if isinstance(v, (list, tuple, set)):
            out: list[str] = []
            for item in v:
                if isinstance(item, str):
                    out.append(item)
                    continue
                name = getattr(item, "name", None)
                if isinstance(name, str):
                    out.append(name)
            return out
        return v

    @field_validator("permissions", mode="before")
    @classmethod
    def normalize_permissions(cls, v):
        # Accepts:
        #   - list of "resource.action" strings (already normalised)
        #   - list of Permission ORM objects   (resource, action attrs)
        #   - list of {"resource": ..., "action": ...} dicts (from JWT payload)
        # Wildcard: resource="*", action="*"  →  "admin.*"
        if v is None:
            return []
        if not isinstance(v, (list, tuple, set)):
            return []

        out: list[str] = []
        seen: set[str] = set()

        for item in v:
            if isinstance(item, str):
                if item not in seen:
                    out.append(item)
                    seen.add(item)
                continue

            # ORM object or dict
            resource = getattr(item, "resource", None) or (item.get("resource") if isinstance(item, dict) else None)
            action = getattr(item, "action", None) or (item.get("action") if isinstance(item, dict) else None)

            if resource is None or action is None:
                continue

            if resource == "*" and action == "*":
                key = "admin.*"
            else:
                key = f"{resource}.{action}"

            if key not in seen:
                out.append(key)
                seen.add(key)

        return out

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Schema for user update"""

    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None


class ServiceTokenRequest(BaseModel):
    """Client credentials request for service-to-service access."""

    client_id: str = Field(..., min_length=1, max_length=100)
    client_secret: str = Field(..., min_length=1, max_length=200)


class ServiceToken(BaseModel):
    """Service access token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    scopes: list[str] = Field(default_factory=list)


class ServiceTokenPayload(BaseModel):
    """Decoded service token payload."""

    sub: str
    scopes: list[str] = Field(default_factory=list)
    iss: str | None = None
    aud: str | None = None
    exp: int | None = None
