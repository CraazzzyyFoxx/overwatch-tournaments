from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from shared.tenancy.hostnames import validate_subdomain_label
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead

# 6-digit hex colour (#RRGGBB) — the format the frontend colour pickers emit and
# the branding derive util consumes.
_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"

__all__ = (
    "WorkspaceRead",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceCustomDomainSet",
    "WorkspaceMemberRoleRead",
    "WorkspaceMemberRead",
    "WorkspaceMemberCreate",
    "WorkspaceMemberUpdate",
    "WorkspaceMemberAutofillResult",
)


class WorkspaceRead(BaseRead):
    slug: str
    name: str
    description: str | None
    icon_url: str | None
    is_active: bool
    branding_enabled: bool = False
    brand_primary: str | None = None
    brand_secondary: str | None = None
    brand_background: str | None = None
    brand_surface: str | None = None
    brand_accent: str | None = None
    brand_foreground: str | None = None
    brand_muted: str | None = None
    brand_border: str | None = None
    brand_ring: str | None = None
    brand_destructive: str | None = None
    subdomain: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    # White-label custom domains (Phase 2). ``custom_domain_verification_token``
    # is exposed so the admin UI can render the required DNS TXT record without
    # a second round-trip; it is not a secret (the TXT record IS public DNS).
    custom_domain: str | None = None
    custom_domain_verified_at: datetime | None = None
    custom_domain_verification_token: str | None = None
    default_division_grid_version_id: int | None
    default_division_grid_version: DivisionGridVersionRead | None = None


class WorkspaceCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon_url: str | None = None
    default_division_grid_version_id: int | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None
    is_active: bool | None = None
    branding_enabled: bool | None = None
    brand_primary: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_secondary: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_background: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_surface: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_accent: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_foreground: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_muted: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_border: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_ring: str | None = Field(default=None, pattern=_HEX_COLOR)
    brand_destructive: str | None = Field(default=None, pattern=_HEX_COLOR)
    subdomain: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    default_division_grid_version_id: int | None = None

    @field_validator(
        "brand_primary",
        "brand_secondary",
        "brand_background",
        "brand_surface",
        "brand_accent",
        "brand_foreground",
        "brand_muted",
        "brand_border",
        "brand_ring",
        "brand_destructive",
        mode="before",
    )
    @classmethod
    def _blank_hex_to_none(cls, value: object) -> object:
        # An empty/whitespace colour means "keep the default" — normalize it to
        # None (which clears the token) instead of failing the #RRGGBB pattern.
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("subdomain")
    @classmethod
    def _validate_subdomain(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return validate_subdomain_label(value)


class WorkspaceCustomDomainSet(BaseModel):
    """Body for ``set_custom_domain``. Normalization/validation of the domain
    itself (FQDN shape, platform-zone rejection) happens in the service layer
    via ``normalize_custom_domain`` so both this RPC and any future caller share
    one source of truth for what counts as a valid custom domain."""

    custom_domain: str = Field(..., min_length=1, max_length=255)


class WorkspaceMemberRoleRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_system: bool
    workspace_id: int | None = None

    class Config:
        from_attributes = True


class WorkspaceMemberRead(BaseRead):
    workspace_id: int
    auth_user_id: int
    role: str
    username: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None
    rbac_roles: list[WorkspaceMemberRoleRead] = Field(default_factory=list)


class WorkspaceMemberCreate(BaseModel):
    auth_user_id: int
    role: str | None = Field(default=None, pattern=r"^(owner|admin|member)$")
    role_ids: list[int] | None = None


class WorkspaceMemberUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(owner|admin|member)$")
    role_ids: list[int] | None = None


class WorkspaceMemberAutofillResult(BaseModel):
    """Result of the ``members_autofill_roles`` action: how many role-less
    members were granted the baseline ``member`` role."""

    assigned: int
