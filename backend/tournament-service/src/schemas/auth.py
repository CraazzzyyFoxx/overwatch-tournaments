import re

from pydantic import BaseModel, EmailStr, Field, field_validator

__all__ = (
    "UserRegister",
    "UserLogin",
    "Token",
    "TokenPayload",
    "RefreshTokenRequest",
    "AuthUser",
    "UserUpdate",
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
    password: str


class Token(BaseModel):
    """Schema for token response"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for JWT token payload"""

    sub: int  # user_id
    email: str
    username: str
    is_superuser: bool = False
    exp: int | None = None


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request"""

    refresh_token: str


class AuthUser(BaseModel):
    """Schema for authenticated user response"""

    id: int
    email: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_superuser: bool
    is_verified: bool
    created_at: str
    updated_at: str | None = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Schema for user update"""

    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
