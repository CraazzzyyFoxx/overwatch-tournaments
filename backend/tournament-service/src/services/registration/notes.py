"""Organizer notes on a registration or a registration team, with private file attachments.

Authorization is the caller's (``src/rpc/registration_notes.py``); this module
owns the rows, the tournament-scoping checks and the S3 key layout. Every write
commits. S3 objects live under ``registration-notes/{tournament_id}/{note_id}/``
-- outside the bucket's public ``avatars/``/``assets/`` prefixes, so they are
only reachable through a presigned URL.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import RegistrationNoteAttachmentRepository, RegistrationNoteRepository
from src.schemas.registration_note import (
    RegistrationNoteAttachmentRead,
    RegistrationNoteCounts,
    RegistrationNoteRead,
)

__all__ = ("ALLOWED_EXTENSIONS", "MAX_ATTACHMENT_SIZE", "MAX_ATTACHMENTS_PER_NOTE", "notes_service")

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_NOTE = 5

#: Extension -> the content type the object is stored and served with. The client's
#: own content type is ignored: browsers disagree on csv/zip, and the extension is
#: what decides how the file opens anyway. No html/svg: nothing renders as a page.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".zip": "application/zip",
}
#: Opened in the browser tab; everything else downloads.
_INLINE_PREFIXES = ("image/", "application/pdf", "text/plain")


def note_prefix(tournament_id: int, note_id: int) -> str:
    return f"registration-notes/{tournament_id}/{note_id}/"


def content_disposition(attachment: models.RegistrationNoteAttachment) -> str:
    kind = "inline" if attachment.content_type.startswith(_INLINE_PREFIXES) else "attachment"
    return f"{kind}; filename*=UTF-8''{quote(attachment.filename)}"


def resolve_upload(filename: str, size: int) -> tuple[str, str, str]:
    """``(clean filename, extension, stored content type)`` for an upload, or 422."""
    name = os.path.basename(filename.replace("\\", "/")).strip()[:255]
    extension = os.path.splitext(name)[1].lower()
    content_type = ALLOWED_EXTENSIONS.get(extension)
    if not name or content_type is None:
        raise HTTPException(
            status_code=422,
            detail=f"File type not allowed (allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))})",
        )
    if size == 0:
        raise HTTPException(status_code=422, detail="File is empty")
    if size > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=422, detail=f"File too large (max {MAX_ATTACHMENT_SIZE} bytes)")
    return name, extension, content_type


def _read(note: models.RegistrationNote) -> RegistrationNoteRead:
    return RegistrationNoteRead(
        id=note.id,
        registration_id=note.registration_id,
        registration_team_id=note.registration_team_id,
        author_id=note.author_id,
        author_username=note.author.username if note.author is not None else None,
        body=note.body,
        created_at=note.created_at,
        edited_at=note.edited_at,
        attachments=[
            RegistrationNoteAttachmentRead(
                id=a.id,
                filename=a.filename,
                content_type=a.content_type,
                size_bytes=a.size_bytes,
                created_at=a.created_at,
            )
            for a in note.attachments
        ],
    )


_LOAD = (selectinload(models.RegistrationNote.author), selectinload(models.RegistrationNote.attachments))
_notes = RegistrationNoteRepository()
_attachments = RegistrationNoteAttachmentRepository()


class RegistrationNoteService:
    async def ensure_target(
        self, session: AsyncSession, *, tournament_id: int, registration_id: int | None, team_id: int | None
    ) -> None:
        """404 unless the target exists in ``tournament_id`` -- an organizer of one event may not annotate another's."""
        model = models.Registration if registration_id is not None else models.RegistrationTeam
        target_id = registration_id if registration_id is not None else team_id
        found = await session.scalar(
            select(model.id).where(model.id == target_id, model.tournament_id == tournament_id)
        )
        if found is None:
            raise HTTPException(status_code=404, detail="Registration not found")

    async def get(self, session: AsyncSession, *, tournament_id: int, note_id: int) -> models.RegistrationNote:
        note = await session.scalar(
            select(models.RegistrationNote)
            .where(models.RegistrationNote.id == note_id, models.RegistrationNote.tournament_id == tournament_id)
            .options(*_LOAD)
        )
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found")
        return note

    async def read(self, session: AsyncSession, *, tournament_id: int, note_id: int) -> RegistrationNoteRead:
        return _read(await self.get(session, tournament_id=tournament_id, note_id=note_id))

    async def list_for(
        self, session: AsyncSession, *, tournament_id: int, registration_id: int | None, team_id: int | None
    ) -> list[RegistrationNoteRead]:
        """Oldest first: a note thread reads top-down like a conversation."""
        target = (
            models.RegistrationNote.registration_id == registration_id
            if registration_id is not None
            else models.RegistrationNote.registration_team_id == team_id
        )
        notes = await session.scalars(
            select(models.RegistrationNote)
            .where(models.RegistrationNote.tournament_id == tournament_id, target)
            .options(*_LOAD)
            .order_by(models.RegistrationNote.created_at, models.RegistrationNote.id)
        )
        return [_read(note) for note in notes]

    async def counts(self, session: AsyncSession, *, tournament_id: int) -> RegistrationNoteCounts:
        rows = await session.execute(
            select(
                models.RegistrationNote.registration_id,
                models.RegistrationNote.registration_team_id,
                func.count(),
            )
            .where(models.RegistrationNote.tournament_id == tournament_id)
            .group_by(models.RegistrationNote.registration_id, models.RegistrationNote.registration_team_id)
        )
        registrations: dict[int, int] = {}
        teams: dict[int, int] = {}
        for registration_id, team_id, count in rows:
            if registration_id is not None:
                registrations[registration_id] = count
            else:
                teams[team_id] = count
        return RegistrationNoteCounts(registrations=registrations, teams=teams)

    async def create(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        registration_id: int | None,
        team_id: int | None,
        author_id: int,
        body: str,
    ) -> RegistrationNoteRead:
        await self.ensure_target(session, tournament_id=tournament_id, registration_id=registration_id, team_id=team_id)
        note = models.RegistrationNote(
            tournament_id=tournament_id,
            registration_id=registration_id,
            registration_team_id=team_id,
            author_id=author_id,
            body=body,
        )
        await _notes.create(session, note)
        await session.commit()
        return await self.read(session, tournament_id=tournament_id, note_id=note.id)

    async def update_body(
        self, session: AsyncSession, *, note: models.RegistrationNote, body: str
    ) -> RegistrationNoteRead:
        note.body = body
        note.edited_at = datetime.now(UTC)
        await session.commit()
        return await self.read(session, tournament_id=note.tournament_id, note_id=note.id)

    async def delete(self, session: AsyncSession, *, note: models.RegistrationNote) -> str:
        """Drop the row (attachments cascade) and commit; returns the S3 prefix the caller clears afterwards."""
        prefix = note_prefix(note.tournament_id, note.id)
        await _notes.delete(session, note)
        await session.commit()
        return prefix

    def new_attachment_key(self, note: models.RegistrationNote, extension: str) -> str:
        if len(note.attachments) >= MAX_ATTACHMENTS_PER_NOTE:
            raise HTTPException(status_code=422, detail=f"A note holds at most {MAX_ATTACHMENTS_PER_NOTE} attachments")
        return f"{note_prefix(note.tournament_id, note.id)}{uuid.uuid4().hex}{extension}"

    async def add_attachment(
        self,
        session: AsyncSession,
        *,
        note_id: int,
        tournament_id: int,
        key: str,
        filename: str,
        content_type: str,
        size: int,
        uploaded_by: int,
    ) -> RegistrationNoteRead:
        await _attachments.create(
            session,
            models.RegistrationNoteAttachment(
                note_id=note_id,
                s3_key=key,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
                uploaded_by=uploaded_by,
            ),
        )
        await session.commit()
        # A fresh read: the identity map still holds the note with its old attachment list.
        session.expire_all()
        return await self.read(session, tournament_id=tournament_id, note_id=note_id)

    def attachment(self, note: models.RegistrationNote, attachment_id: int) -> models.RegistrationNoteAttachment:
        found = next((a for a in note.attachments if a.id == attachment_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        return found

    async def delete_attachment(
        self, session: AsyncSession, *, note: models.RegistrationNote, attachment: models.RegistrationNoteAttachment
    ) -> tuple[RegistrationNoteRead, str]:
        """Drop the row and commit; returns the fresh note and the S3 key the caller deletes afterwards."""
        key, tournament_id, note_id = attachment.s3_key, note.tournament_id, note.id
        note.attachments.remove(attachment)
        await session.commit()
        session.expire_all()
        return await self.read(session, tournament_id=tournament_id, note_id=note_id), key


notes_service = RegistrationNoteService()
