"""
Generic OAuth schemas for multiple providers
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from shared.core import pagination

from .auth import Token

__all__ = (
    "OAuthProvider",
    "OAuthProviderAvailability",
    "OAuthURL",
    "OAuthCallbackRequest",
    "OAuthCallbackResult",
    "OAuthLinkResult",
    "OAuthUserInfo",
    "OAuthConnectionRead",
    "OAuthConnectionAdminRead",
    "OAuthConnectionListQueryParams",
    "OAuthConnectionListParams",
    "PlayerLinkRequest",
    "PlayerLinkResponse",
    "LinkedPlayer",
)


class OAuthProvider(str, Enum):
    """Supported OAuth providers"""

    DISCORD = "discord"
    TWITCH = "twitch"
    BATTLENET = "battlenet"
    GOOGLE = "google"
    GITHUB = "github"
    # Add more providers as needed


class OAuthURL(BaseModel):
    """OAuth URL response"""

    provider: OAuthProvider
    url: str
    state: str


class OAuthProviderAvailability(BaseModel):
    """OAuth provider availability response"""

    provider: OAuthProvider


class OAuthCallbackRequest(BaseModel):
    """OAuth callback request"""

    code: str
    state: str


class OAuthCallbackResult(Token):
    """OAuth callback response: the session (or a handoff to it) plus the
    decoded, verified state fields the frontend needs to redirect the user
    back to the tenant subdomain/custom domain that started the flow (the
    callback itself always lands on the one fixed apex callback URL, never
    on ``origin``).

    ``mode="cookie"`` (platform apex / ``.owt`` subdomain) carries the raw
    tokens, same as before -- the frontend sets cookies directly.
    ``mode="ticket"`` (custom domain) carries a one-time Redis ``ticket``
    instead: cookies set on the apex are not readable on a custom domain, so
    the tokens themselves never leave identity-svc's Redis until the custom
    domain redeems the ticket via ``rpc.identity.sso_exchange`` (see
    ``sso_tickets``). Token fields are optional because ticket mode omits
    them entirely -- never populate both a ticket AND raw tokens.
    """

    mode: Literal["cookie", "ticket"] = "cookie"
    access_token: str | None = None
    refresh_token: str | None = None
    ticket: str | None = None
    origin: str
    redirect: str
    action: str | None = None


class OAuthLinkResult(BaseModel):
    """Result of an account-linking attempt (``oauth_flows.link``, Task 10R).

    ``mode="linked"`` (default; platform apex / a ``.owt`` subdomain): the
    provider identity was attached directly to the LIVE bearer-authenticated
    user -- ``message``/``provider``/``username`` describe what was linked.

    ``mode="link_ticket"`` (a workspace custom domain): nothing was linked.
    This response is produced by the ONE fixed apex callback, which shares
    no cookie with a custom domain (see ``oauth_flows`` module docstring), so
    there is no live session here to attach the provider identity to.
    ``ticket`` carries a single-use handle to that PROVIDER identity only
    (never a site user id -- SECURITY INVARIANT #2); the custom domain's own
    frontend route redeems it (``rpc.identity.link_complete``, itself
    bearer-authenticated there) against ITS OWN live session. ``message``/
    ``provider``/``username`` are omitted in this mode.
    """

    mode: Literal["linked", "link_ticket"] = "linked"
    message: str | None = None
    provider: str | None = None
    username: str | None = None
    ticket: str | None = None
    origin: str
    redirect: str
    action: str | None = None


class OAuthUserInfo(BaseModel):
    """Generic OAuth user information"""

    provider: OAuthProvider
    provider_user_id: str
    email: str | None = None
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    raw_data: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True


class OAuthConnectionRead(BaseModel):
    """OAuth connection info (safe fields only, no tokens)."""

    id: int
    provider: OAuthProvider
    provider_user_id: str
    email: str | None = None
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class OAuthConnectionAdminRead(OAuthConnectionRead):
    """OAuth connection with owner info for admin views."""

    auth_user_id: int
    auth_user_email: str | None = None
    auth_user_username: str | None = None
    token_expires_at: datetime | None = None


_OAUTH_CONN_SORT = Literal["id", "created_at", "provider", "provider_user_id", "username", "email"]


class OAuthConnectionListQueryParams(pagination.PaginationSortQueryParams[_OAUTH_CONN_SORT]):
    """Query params for the admin OAuth-connections list (GET /rbac/oauth-connections)."""

    per_page: int = Field(default=20, ge=-1, le=100)
    sort: _OAUTH_CONN_SORT = "created_at"
    order: pagination.SortOrder = pagination.SortOrder.DESC
    search: str | None = None
    provider: str | None = None
    auth_user_id: int | None = None


@dataclass
class OAuthConnectionListParams(pagination.PaginationSortParams):
    per_page: int = 20
    search: str | None = None
    provider: str | None = None
    auth_user_id: int | None = None


class PlayerLinkRequest(BaseModel):
    """Request to link player to auth user"""

    player_id: int
    is_primary: bool = True


class LinkedPlayer(BaseModel):
    """Linked player information"""

    player_id: int
    player_name: str
    is_primary: bool
    linked_at: str

    class Config:
        from_attributes = True


class PlayerLinkResponse(BaseModel):
    """Response after linking player"""

    message: str
    player: LinkedPlayer
