from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from shared.schemas.quota import QuotaLimitsWrite, QuotaScope
from shared.services.ontology import normalize_disciplines_enabled
from shared.tenancy.hostnames import validate_subdomain_label
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead

# 6-digit hex colour (#RRGGBB) — the format the frontend colour pickers emit and
# the branding derive util consumes.
_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"

# A Discord snowflake: 17-19 digits (19 already reaches ~2084). 20 digits would
# not fit the BigInteger the migration's downgrade casts back to. Kept as a string
# end to end because it exceeds 2**53 and a float round-trip would corrupt it. No
# `max_length`: the pattern already caps the value at 19 characters, and both in
# the public schema would advertise contradictory bounds.
_DISCORD_SNOWFLAKE = r"^\d{17,19}$"

# Which hosts each community link may point at (``www.`` stripped before the
# check). An allowlist, not a generic URL check: the field is labelled "Discord"
# in the admin form, so a Twitch link in it is a typo, not a free choice.
_LINK_HOSTS: dict[str, tuple[str, ...]] = {
    "discord_url": ("discord.gg", "discord.com"),
    "twitch_url": ("twitch.tv",),
    "boosty_url": ("boosty.to",),
}

__all__ = (
    "WorkspaceListItem",
    "WorkspaceRead",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceCustomDomainSet",
    "WorkspaceDiscordGuildVerify",
    "WorkspaceDiscordGuildOption",
    "WorkspaceDiscordGuildsRead",
    "WorkspaceVerificationSet",
    "WorkspaceQuotaSet",
    "WorkspaceOwnerRead",
    "WorkspaceStaffMember",
    "WorkspaceOwnerSet",
    "WorkspaceOwnerTransfer",
    "WorkspaceMemberRoleRead",
    "WorkspaceMemberRead",
    "WorkspaceMemberCreate",
    "WorkspaceMemberUpdate",
    "WorkspaceMemberAutofillResult",
)


class WorkspaceListItem(BaseRead):
    """One row of ``workspaces.list``: everything but the grids, which a list of every workspace cannot afford."""

    slug: str
    name: str
    description: str | None
    icon_url: str | None
    # Public community profile, rendered by the workspace landing page.
    # ``about`` is Markdown.
    tagline: str | None = None
    about: str | None = None
    discord_url: str | None = None
    twitch_url: str | None = None
    boosty_url: str | None = None
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
    # Custom domains. ``custom_domain_verification_token``
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
    # Who proved ownership and when -- same public-exposure precedent as
    # custom_domain_verified_at just above. discord_guild_verified_by_auth_user_id
    # stays off this model: unlike a guild id or a DNS token, an internal
    # auth_user_id is not published.
    discord_guild_verified_at: datetime | None = None
    # Self-service trust tier. Public because the frontend renders
    # it as a badge and derives the "not listed on the home page yet" notice
    # from it; ``trusted`` is also exactly what the public directory filters on,
    # so it is already observable from the outside.
    verification_status: str = "unverified"
    default_division_grid_versions: dict[str, int] = Field(default_factory=dict)
    #: The workspace's enabled games as stored; a read never invents one.
    disciplines_enabled: list[str]
    # See ``shared.models.tenancy.workspace.Workspace.newcomer_scope``.
    newcomer_scope: Literal["global", "workspace"] = "global"


class WorkspaceRead(WorkspaceListItem):
    """One workspace, with the effective division grid of each of its games."""

    effective_division_grid_versions: dict[str, DivisionGridVersionRead] = Field(default_factory=dict)


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon_url: str | None = None


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Same bounds as ``WorkspaceCreate``; stripped first, so a name of spaces is no name.
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    icon_url: str | None = None
    # Public community profile. Blank input clears the field (``_blank_to_none``);
    # the three links must be https and point at their own service.
    tagline: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=4000)
    discord_url: str | None = Field(default=None, max_length=512)
    twitch_url: str | None = Field(default=None, max_length=512)
    boosty_url: str | None = Field(default=None, max_length=512)
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
    disciplines_enabled: list[str] | None = None
    newcomer_scope: Literal["global", "workspace"] | None = None

    @field_validator("disciplines_enabled")
    @classmethod
    def _disciplines_enabled(cls, value: list[str] | None) -> list[str]:
        if value is None:
            raise ValueError("disciplines_enabled must be a list")
        return normalize_disciplines_enabled(value)

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

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("tagline", "about", mode="before")
    @classmethod
    def _blank_text_to_none(cls, value: object) -> object:
        # Same contract as the colours above: a cleared textarea clears the field.
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("discord_url", "twitch_url", "boosty_url", mode="before")
    @classmethod
    def _validate_social_link(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, str):
            return value
        url = value.strip()
        if not url:
            return None
        hosts = _LINK_HOSTS[str(info.field_name)]
        parts = urlsplit(url)
        # https only: these render as outbound links on a public page, and an
        # http one would be a downgrade the organizer did not notice typing.
        host = parts.hostname or ""
        host = host.removeprefix("www.")
        if parts.scheme != "https" or host not in hosts:
            raise ValueError(f"must be an https link to {' or '.join(hosts)}")
        return url


class WorkspaceCustomDomainSet(BaseModel):
    """Body for ``set_custom_domain``. The domain itself (FQDN shape,
    platform-zone rejection) is validated in the service layer by
    ``normalize_custom_domain``."""

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
    ``discord_guild_verify`` is handed a snowflake the caller can actually prove."""

    guild_id: str
    name: str
    icon_url: str | None = None
    owner: bool
    can_manage: bool


class WorkspaceDiscordGuildsRead(BaseModel):
    guilds: list[WorkspaceDiscordGuildOption] = Field(default_factory=list)
    #: The caller's Discord connection has no usable OAuth token: the empty
    #: list means "re-link Discord", not "you administer nothing".
    relink_required: bool = False


class WorkspaceVerificationSet(BaseModel):
    """Body for the superuser-only ``verification_set``. The three tiers are a
    convention, not a DB enum (the column is a plain ``String(16)``) -- this
    Literal is where the convention is actually enforced."""

    verification_status: Literal["unverified", "verified", "trusted"]


class WorkspaceQuotaSet(BaseModel):
    """Body for ``quota_set``: one scope's override, or its removal.

    ``limits`` is the shared wire payload every quota writer speaks, so the
    five dimensions are declared once; an all-null payload deletes the override
    row rather than pinning five nulls, which is how a tenant gets back onto
    its plan.
    """

    scope: QuotaScope
    limits: QuotaLimitsWrite = Field(default_factory=QuotaLimitsWrite)


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


class WorkspaceStaffMember(BaseModel):
    """One publicly credited organizer of a workspace.

    A NAME and a role, nothing else: unlike ``WorkspaceOwnerRead`` above this
    model IS served anonymously, so it carries no account identifier, no email
    and no auth-user id — only the player name the site already shows on every
    roster and profile page.
    """

    role: Literal["owner", "admin", "referee"]
    name: str


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


# The workspace system roles (``shared.rbac.catalog.WORKSPACE_SYSTEM_ROLE_NAMES``);
# a name outside them has no role to resolve to.
_SYSTEM_ROLE = r"^(owner|admin|referee|host|player)$"


class WorkspaceMemberCreate(BaseModel):
    auth_user_id: int
    role: str | None = Field(default=None, pattern=_SYSTEM_ROLE)
    role_ids: list[int] | None = None


class WorkspaceMemberUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=_SYSTEM_ROLE)
    role_ids: list[int] | None = None


class WorkspaceMemberAutofillResult(BaseModel):
    """Result of the ``members_autofill_roles`` action: how many role-less
    members were granted the baseline ``member`` role."""

    assigned: int
