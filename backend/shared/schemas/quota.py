"""Wire contracts for the ``quota`` schema's admin surface.

The limit vocabulary is closed and typed on purpose: ``extra="forbid"`` makes a
misspelled dimension fail the write instead of silently reading as "unlimited",
which is exactly how the per-key limits this replaces became fiction.

``None`` keeps the meaning it has in the tables -- "unset at this level", i.e.
inherit in an override row and unlimited in a plan row -- so a payload that
omits a field leaves it inherited rather than zeroing it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "QUOTA_SCOPES",
    "QuotaLimitsPayload",
    "QuotaOperationRead",
    "QuotaOperationWrite",
    "QuotaPlanLimitRead",
    "QuotaPlanRead",
    "QuotaPlanWrite",
    "QuotaScope",
    "QuotaScopeUsage",
    "QuotaUsageRead",
)

QuotaScope = Literal["workspace", "key", "session"]
QUOTA_SCOPES: tuple[QuotaScope, ...] = ("workspace", "key", "session")


class QuotaLimitsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests_per_minute: int | None = Field(None, ge=0)
    heavy_per_day: int | None = Field(None, ge=0)
    concurrent_heavy: int | None = Field(None, ge=0)
    max_upload_bytes: int | None = Field(None, ge=0)
    max_items_per_request: int | None = Field(None, ge=0)

    def as_dict(self) -> dict[str, int | None]:
        return self.model_dump()

    @property
    def is_empty(self) -> bool:
        """An all-null payload means "drop the override", not "set five nulls"."""
        return all(value is None for value in self.model_dump().values())


class QuotaPlanLimitRead(QuotaLimitsPayload):
    scope: QuotaScope


class QuotaPlanRead(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    limits: list[QuotaPlanLimitRead] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class QuotaPlanWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    limits: list[QuotaPlanLimitRead] = Field(default_factory=list)


class QuotaOperationRead(BaseModel):
    id: int
    slug: str
    cost: int
    enabled: bool
    description: str | None = None


class QuotaOperationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.]*$")
    cost: int = Field(1, ge=0)
    enabled: bool = True
    description: str | None = None


class QuotaScopeUsage(BaseModel):
    """One bucket's effective ceiling next to what has been spent against it."""

    scope: QuotaScope
    requests_per_minute: int | None = None
    requests_used: int = 0
    requests_reset_in: int | None = None
    heavy_per_day: int | None = None
    heavy_used: int = 0
    heavy_reset_in: int | None = None
    concurrent_heavy: int | None = None
    concurrent_used: int = 0
    max_upload_bytes: int | None = None
    max_items_per_request: int | None = None


class QuotaUsageRead(BaseModel):
    plan_slug: str | None = None
    workspace_id: int | None = None
    scopes: list[QuotaScopeUsage] = Field(default_factory=list)
