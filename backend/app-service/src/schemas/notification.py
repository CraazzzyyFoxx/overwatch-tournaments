"""Read models for the notification inbox and the announcement banner.

``NotificationItem`` deliberately carries no rendered text for system kinds:
the row stores ``kind`` + a payload snapshot and the frontend renders
``t("notifications.kinds.<kind>", payload)``, so a translation fix reaches
rows that were written months ago. Announcements are the exception -- their
operator-written text lives *inside* the payload, one entry per locale.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.services.notifications import BROADCASTABLE_KINDS
from src.schemas.base import BaseRead

#: The locales a workspace may pick for its channel posts, mirroring
#: ``shared.services.notifications.SUPPORTED_LOCALES``.
NotificationLocale = Literal["ru", "en"]

__all__ = (
    "NotificationItem",
    "NotificationInboxRead",
    "NotificationMarkRead",
    "NotificationMarkReadResult",
    "NotificationDelete",
    "NotificationDeleteResult",
    "NotificationAdminItem",
    "NotificationAdminPage",
    "NotificationRetire",
    "NotificationRetireResult",
    "NotificationDmGroups",
    "NotificationDmGroupsUpdate",
    "NotificationPreferencesRead",
    "NotificationPreferencesUpdate",
    "NotificationWorkspaceConfigRead",
    "NotificationWorkspaceConfigUpdate",
)


class NotificationItem(BaseRead):
    model_config = ConfigDict(from_attributes=True)

    audience: str
    kind: str
    # ``payload_json`` on the row; ``payload`` on the wire -- the column name's
    # ``_json`` suffix is a storage detail, and the frontend interpolates this
    # object into the kind's i18n message.
    payload: dict[str, Any] = Field(validation_alias="payload_json")
    workspace_id: int | None = None
    published_at: datetime
    expires_at: datetime | None = None
    # Whether *this* caller has a read mark on the row -- the inbox page
    # computes it per identity (``NotificationRepository.page``). Defaults to
    # ``False`` for the banner read, which by construction only ever serves
    # rows the viewer has not dismissed.
    is_read: bool = False


class NotificationInboxRead(BaseModel):
    """One inbox round trip: the page, the badge count and the continuation.

    The bell renders the count and the list together on every open, so serving
    them from two endpoints would double the requests for a header component
    that mounts on every page.
    """

    items: list[NotificationItem]
    unread_count: int
    # ``None`` means "this was the last page". Opaque: the pair it encodes is an
    # ordering detail, and a client that parses it starts depending on the sort key.
    next_cursor: str | None = None


class NotificationMarkRead(BaseModel):
    """``ids=None`` marks the whole visible inbox (the "mark all read" button)."""

    ids: list[int] | None = None


class NotificationMarkReadResult(BaseModel):
    # ``marked`` counts the rows that actually landed: ids outside the caller's
    # audience contribute nothing, and a repeat call marks nothing at all.
    marked: int
    unread_count: int


class NotificationDelete(BaseModel):
    """``ids=None`` deletes the whole visible inbox; ``only_read`` narrows it.

    The two together are the "clear read" button, which must not be able to
    swallow a notification the user has not opened yet.
    """

    ids: list[int] | None = None
    only_read: bool = False


class NotificationDeleteResult(BaseModel):
    # ``deleted`` counts the rows that actually left this inbox: ids outside
    # the caller's audience contribute nothing, and a repeat call deletes
    # nothing at all.
    deleted: int
    unread_count: int


class NotificationAdminItem(BaseRead):
    """One produced row as an operator sees it.

    Separate from ``NotificationItem`` because it answers a different question:
    the inbox model is "what am I being told", this one is "what did my
    workspace send, to whom, and is it still live". Hence ``recipient`` — which
    the inbox has no business carrying, since there it is always the caller —
    and no ``is_read``, which is a fact about a viewer this screen does not have.
    """

    model_config = ConfigDict(from_attributes=True)

    kind: str
    payload: dict[str, Any] = Field(validation_alias="payload_json")
    recipient_auth_user_id: int | None = None
    #: The recipient's current username, LEFT-joined at read time -- ``None``
    #: when the audience is not a single user, or the account is gone.
    recipient_username: str | None = None
    source_workspace_id: int | None = None
    published_at: datetime
    #: Set (and in the past) means retired: the row no longer reaches an inbox.
    expires_at: datetime | None = None


class NotificationAdminPage(BaseModel):
    items: list[NotificationAdminItem]
    #: ``None`` on the last page; opaque, like the inbox cursor.
    next_cursor: str | None = None


class NotificationRetire(BaseModel):
    """Which of this workspace's notifications to take out of circulation.

    ``ids`` and ``kind`` are filters over the same scoped statement and may be
    combined. Naming neither is rejected — "retire everything this workspace
    ever sent" must be spelled out one kind at a time, not reached by omission.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: int
    ids: list[int] | None = None
    kind: str | None = None


class NotificationRetireResult(BaseModel):
    #: Rows that were live and now are not; a repeat call answers 0.
    retired: int


class NotificationDmGroups(BaseModel):
    """The three Discord-DM switches, defaults already filled in.

    Spelled out as fields rather than a free dict because this is a public
    response shape: the client renders one toggle per group and the generated
    OpenAPI has to name them. ``test_notification_preferences_rpc`` pins the
    field set against ``NOTIFICATION_GROUPS``, so a fourth group cannot be
    added upstream without this following.
    """

    tournament: bool
    matches: bool
    team: bool


class NotificationDmGroupsUpdate(BaseModel):
    """A partial edit: an omitted group keeps whatever is stored for it."""

    model_config = ConfigDict(extra="forbid")

    tournament: bool | None = None
    matches: bool | None = None
    team: bool | None = None


class NotificationPreferencesRead(BaseModel):
    discord_dm: NotificationDmGroups
    #: False = the switches change nothing yet, so the UI offers the link flow
    #: instead of silently doing nothing.
    discord_linked: bool


class NotificationPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discord_dm: NotificationDmGroupsUpdate


class NotificationWorkspaceConfigRead(BaseModel):
    """Where this workspace's broadcasts go, plus what the picker needs.

    Discord snowflakes are strings: they exceed 2^53 and a JSON number loses
    precision in the browser, the same way ``discord_guild_id`` is already
    carried.
    """

    workspace_id: int
    #: The verified guild, if any -- without it no channel may be stored.
    discord_guild_id: str | None = None
    discord_channel_id: str | None = None
    locale: str
    broadcast_kinds: list[str]
    #: Everything that *may* be enabled, so the screen renders the checkboxes
    #: without a second source of truth for the kind list.
    broadcastable_kinds: list[str]


class NotificationWorkspaceConfigUpdate(BaseModel):
    """The settings form, submitted whole -- it edits one row of three values."""

    model_config = ConfigDict(extra="forbid")

    discord_channel_id: str | None = None
    locale: NotificationLocale = "ru"
    broadcast_kinds: list[str] = Field(default_factory=list)

    @field_validator("broadcast_kinds")
    @classmethod
    def _known_kinds(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - BROADCASTABLE_KINDS)
        if unknown:
            raise ValueError(f"not broadcastable: {', '.join(unknown)}")
        # Deduplicated and ordered so the stored JSON is stable across saves.
        return [kind for kind in sorted(BROADCASTABLE_KINDS) if kind in set(value)]
