"""The chat wire shape. Identical for every room kind, by construction."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = (
    "ChatEnvelope",
    "ChatMessageRead",
    "ChatMuteInput",
    "ChatMuteRead",
    "ChatPostInput",
    "ChatSettings",
    "ChatSettingsInput",
    "ChatViewer",
)

#: Server-side ceiling on one message. The client mirrors it as guidance; this
#: is the gate.
MAX_BODY_LENGTH = 500
#: Anything longer is refused before sanitizing — see ``service._sanitize``.
MAX_RAW_BODY_LENGTH = 2000
HISTORY_DEFAULT = 50
HISTORY_MAX = 200
#: Longest mute an organizer can set in one call (a week). Longer than any
#: single match day, short enough that "indefinite" stays a deliberate choice.
MAX_MUTE_MINUTES = 7 * 24 * 60


class ChatMessageRead(BaseModel):
    id: int
    created_at: datetime
    auth_user_id: int
    author_name: str
    author_role: str
    body: str
    #: The author's avatar AS IT IS NOW, unlike ``author_name``, which is the
    #: snapshot taken when the message was sent. A name is part of what was
    #: said and has to stay readable as it was; a face is just the account's
    #: current one, so it is resolved on read and costs no column.
    author_avatar_url: str | None = None


class ChatSettings(BaseModel):
    spectators_can_read: bool


class ChatMuteRead(BaseModel):
    auth_user_id: int
    muted_until: datetime | None
    reason: str | None
    created_by_auth_user_id: int
    created_at: datetime


class ChatViewer(BaseModel):
    """Everything the panel needs to decide what to render, in the same reply.

    Without it the client would have to infer "may I type here" from the
    absence of an error on a write it has not made yet.
    """

    role: str
    can_write: bool
    can_moderate: bool
    muted_until: datetime | None = None


class ChatEnvelope(BaseModel):
    messages: list[ChatMessageRead]
    settings: ChatSettings
    viewer: ChatViewer
    #: Moderators only; empty for everybody else — who is muted is not public.
    mutes: list[ChatMuteRead] = Field(default_factory=list)


class ChatPostInput(BaseModel):
    body: str


class ChatSettingsInput(BaseModel):
    spectators_can_read: bool


class ChatMuteInput(BaseModel):
    #: ``None`` mutes until an organizer lifts it.
    minutes: int | None = Field(default=None, ge=1, le=MAX_MUTE_MINUTES)
    reason: str | None = Field(default=None, max_length=200)
