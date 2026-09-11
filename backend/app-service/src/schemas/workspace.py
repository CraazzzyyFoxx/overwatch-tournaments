from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.schemas.roster_slots import RosterSlotsField
from shared.tenancy.hostnames import validate_subdomain_label
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead

# 6-digit hex colour (#RRGGBB) — the format the frontend colour pickers emit and
# the branding derive util consumes.
_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"

# A Discord snowflake: 17-19 digits. 19 already reaches ~2084, and the column this
# used to live in was BigInteger, which tops out at 19 digits -- so 20 was never
# storable, and permitting it would let through a value the migration's downgrade
# cannot cast back. Kept as a string end to end because it exceeds 2**53 and a float
# round-trip would corrupt it. No `max_length` accompanies this pattern: it caps the
# value at 19 characters already, so the `String(32)` column width could never bind,
# and shipping both into the public schema would advertise contradictory bounds.
_DISCORD_SNOWFLAKE = r"^\d{17,19}$"

__all__ = (
    "WorkspaceRead",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceCustomDomainSet",
    "WorkspaceDiscordGuildVerify",
    "WorkspaceDiscordGuildOption",
    "WorkspaceDiscordGuildsRead",
    "WorkspaceVerificationSet",
    "WorkspaceOwnerRead",
    "WorkspaceOwnerSet",
    "WorkspaceOwnerTransfer",
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
    # Excludes this workspace from another workspace's member picker and from
    # the anonymous listing; a member still sees it (`WorkspaceService.get_all`).
    is_hidden: bool = False
    timezone: str = "Europe/Moscow"
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
    # The organizer's Discord guild. Public for the same reason
    # `custom_domain_verification_token` above is: it is not a secret -- every
    # Discord message link is `discord.com/channels/<guild_id>/<channel_id>/<id>`.
    # A genuinely secret integration value must NOT follow this path; it needs an
    # authenticated admin read model.
    discord_guild_id: str | None = None
    # Who proved ownership and when (self-service design §4.1) -- same
    # public-exposure precedent as custom_domain_verified_at just above.
    # discord_guild_verified_by_auth_user_id stays off this model: unlike a
    # guild id or a DNS token, an arbitrary internal auth_user_id is not
    # something this design chooses to publish.
    discord_guild_verified_at: datetime | None = None
    # Self-service trust tier (design §4.2). Public because the frontend renders
    # it as a badge and derives the "not listed on the home page yet" notice
    # from it; ``trusted`` is also exactly what the public directory filters on,
    # so it is already observable from the outside.
    verification_status: str = "unverified"
    default_division_grid_version_id: int | None
    default_division_grid_version: DivisionGridVersionRead | None = None
    default_roster_slots_json: dict[str, int] | None = None
    # See ``shared.models.tenancy.workspace.Workspace.newcomer_scope``.
    newcomer_scope: Literal["global", "workspace"] = "global"


class WorkspaceCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon_url: str | None = None
    default_division_grid_version_id: int | None = None
    default_roster_slots_json: RosterSlotsField = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None
    is_active: bool | None = None
    is_hidden: bool | None = None
    timezone: str | None = None
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
    # Edited in place, unlike `default_division_grid_version_id` above: a roster
    # shape has no activation semantics, so it needs no dedicated endpoint.
    default_roster_slots_json: RosterSlotsField = None
    newcomer_scope: Literal["global", "workspace"] | None = None

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

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        # The column is NOT NULL: None means "field untouched"; a blank or
        # unknown zone is rejected rather than silently written as NULL.
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value!r}") from exc
        return value


class WorkspaceCustomDomainSet(BaseModel):
    """Body for ``set_custom_domain``. Normalization/validation of the domain
    itself (FQDN shape, platform-zone rejection) happens in the service layer
    via ``normalize_custom_domain`` so both this RPC and any future caller share
    one source of truth for what counts as a valid custom domain."""

    custom_domain: str = Field(..., min_length=1, max_length=255)


class WorkspaceDiscordGuildVerify(BaseModel):
    """Body for ``discord_guild_verify``. The snowflake pattern gates shape
    only -- the actual proof of administration happens server-side via
    ``rpc.identity.oauth_discord_guilds``, not here. Clearing a verified claim
    is a separate verb (``discord_guild_clear``), not a blank ``guild_id``."""

    guild_id: str = Field(..., pattern=_DISCORD_SNOWFLAKE)


class WorkspaceDiscordGuildOption(BaseModel):
    """One guild the caller administers, as reported by
    ``rpc.identity.oauth_discord_guilds``. Feeds the settings guild picker, so
    ``discord_guild_verify`` can be handed a snowflake the caller can actually
    prove — instead of a free-text field that only fails after the fact."""

    guild_id: str
    name: str
    icon_url: str | None = None
    owner: bool
    can_manage: bool


class WorkspaceDiscordGuildsRead(BaseModel):
    guilds: list[WorkspaceDiscordGuildOption] = Field(default_factory=list)


class WorkspaceVerificationSet(BaseModel):
    """Body for the superuser-only ``verification_set``. The three tiers are a
    convention, not a DB enum (the column is a plain ``String(16)``) -- this
    Literal is where the convention is actually enforced."""

    verification_status: Literal["unverified", "verified", "trusted"]


class WorkspaceOwnerRead(BaseModel):
    """The accountable owner of a workspace (``Workspace.owner_id``), resolved to
    a person.

    Deliberately NOT a field on ``WorkspaceRead``: that model is served
    anonymously (``GET /api/v1/workspaces/{id}``, and the list is publicly
    cached at the edge), so an owner's username and email sit behind the same
    ``workspace.update`` gate as the Discord role/channel reads -- for the same
    reason ``discord_guild_verified_by_auth_user_id`` was kept off the public
    model.

    ``username``/``email`` are optional so a workspace whose owner row vanished
    between the two reads still answers with the id it has, rather than 500.
    """

    auth_user_id: int
    username: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None


class WorkspaceOwnerSet(BaseModel):
    """Body for the superuser-only ``owner_set``. ``None`` clears the stamp --
    a workspace with nobody on the hook is a real state (every workspace
    predating self-service creation is in it), so it has to be reachable, not
    only escapable."""

    auth_user_id: int | None = None


class WorkspaceOwnerTransfer(BaseModel):
    """Body for ``owner_transfer``. Not nullable, unlike ``WorkspaceOwnerSet``:
    a hand-off has a recipient by definition, and "leave nobody accountable" is
    the superuser-only clear on ``owner_set``, not a transfer."""

    auth_user_id: int


class WorkspaceMemberRoleRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_system: bool
    workspace_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkspaceMemberRead(BaseRead):
    workspace_id: int
    auth_user_id: int
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
