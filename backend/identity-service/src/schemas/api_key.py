from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = (
    "ApiKeyCreate",
    "ApiKeyCreateResponse",
    "ApiKeyRead",
    "ApiKeyTokenInfo",
    "ApiKeyUpdate",
)


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    workspace_id: int = Field(..., gt=0)
    expires_at: datetime | None = None


class ApiKeyUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyRead(BaseModel):
    id: int
    name: str
    workspace_id: int
    public_id: str
    scopes: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    config_policy: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyRead
    key: str


class ApiKeyTokenInfo(BaseModel):
    id: int
    public_id: str
    workspace_id: int
    scopes: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    config_policy: dict[str, Any] = Field(default_factory=dict)
