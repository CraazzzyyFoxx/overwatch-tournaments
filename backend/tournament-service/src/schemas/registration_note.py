"""Staff-only notes (with file attachments) on a registration or a registration team.

Never part of a public or player-facing read: every subject serving these is
gated on the workspace's ``registration``/``team`` permissions.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

__all__ = (
    "RegistrationNoteAttachmentRead",
    "RegistrationNoteAttachmentUrl",
    "RegistrationNoteCounts",
    "RegistrationNoteCreate",
    "RegistrationNoteRead",
    "RegistrationNoteUpdate",
)

#: Long enough for a written-up dispute, short enough that a note is not a document store.
MAX_NOTE_BODY = 20_000


class RegistrationNoteAttachmentRead(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class RegistrationNoteRead(BaseModel):
    id: int
    registration_id: int | None
    registration_team_id: int | None
    author_id: int | None
    #: ``None`` once the author's account is gone.
    author_username: str | None
    body: str
    created_at: datetime
    edited_at: datetime | None
    attachments: list[RegistrationNoteAttachmentRead]


class RegistrationNoteCreate(BaseModel):
    registration_id: int | None = None
    registration_team_id: int | None = None
    body: str = Field(min_length=1, max_length=MAX_NOTE_BODY)

    @model_validator(mode="after")
    def _one_target(self) -> RegistrationNoteCreate:
        if (self.registration_id is None) == (self.registration_team_id is None):
            raise ValueError("exactly one of registration_id / registration_team_id is required")
        return self


class RegistrationNoteUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_NOTE_BODY)


class RegistrationNoteCounts(BaseModel):
    """Notes per target across one tournament, for the list views' badges. Targets without notes are absent."""

    registrations: dict[int, int]
    teams: dict[int, int]


class RegistrationNoteAttachmentUrl(BaseModel):
    #: Presigned, short-lived GET of the private object.
    url: str
