"""Organizer notes (with private file attachments) on registrations and registration teams.

Every route is tournament-scoped: the gateway sends the tournament as
``data["id"]`` (IDParam) and the workspace is resolved from it. The permission
resource follows the note's target -- ``registration`` for a player's
registration, ``team`` for a registration team -- the same resources the
surrounding admin screens gate on:

* read (list, counts, attachment URL): ``<resource>.read``;
* write a note or attach to it: ``<resource>.update``; editing a note's body and
  attaching files is its author's alone;
* delete a note or one of its files: its author (with ``update``), or anyone
  holding ``<resource>.delete``.

S3 ordering: an upload writes the object before the row, and deletes the object
again when the row write fails; a delete commits the row first and removes the
objects afterwards, outside the transaction, so a failed S3 call leaves only an
orphan object, never a row pointing at missing bytes.
"""

from __future__ import annotations

import base64
import math
from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from loguru import logger as _log

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src.core import auth
from src.rpc._helpers import _dump, _identity, _path_int, _payload, _q1, _require_id, _run
from src.rpc._s3 import get_s3
from src.schemas.registration_note import (
    RegistrationNoteAttachmentUrl,
    RegistrationNoteCreate,
    RegistrationNoteUpdate,
)
from src.services.registration import notes as notes_module
from src.services.registration.notes import notes_service

#: The longest base64 text that can decode to at most ``MAX_ATTACHMENT_SIZE`` bytes.
_MAX_B64 = 4 * math.ceil(notes_module.MAX_ATTACHMENT_SIZE / 3)
#: Long enough to open the file, short enough that a leaked link soon dies.
_URL_TTL_SECONDS = 300


def _resource(registration_id: int | None) -> str:
    return "registration" if registration_id is not None else "team"


async def _gate(session: Any, data: dict[str, Any]) -> tuple[Any, int, int]:
    """``(user, tournament_id, workspace_id)``; 404 on a missing tournament. No permission checked yet."""
    user = _identity(data)
    tournament_id = _require_id(data)
    ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
    return user, tournament_id, ws_id


async def _note_gate(
    session: Any, data: dict[str, Any], action: str | None
) -> tuple[Any, int, models.RegistrationNote]:
    """The note in ``data["note_id"]`` of this tournament, with ``<resource>.<action>`` checked against it
    (``None``: the caller checks, as the deletes do through :func:`_ensure_may_delete`)."""
    user, tournament_id, ws_id = await _gate(session, data)
    note = await notes_service.get(session, tournament_id=tournament_id, note_id=_path_int(data, "note_id"))
    if action is not None:
        ensure_workspace_permission(user, ws_id, _resource(note.registration_id), action)
    return user, ws_id, note


def _ensure_author(user: Any, note: models.RegistrationNote) -> None:
    if note.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the note's author may change it")


def _ensure_may_delete(user: Any, ws_id: int, note: models.RegistrationNote) -> None:
    """Author with ``<resource>.update``, or anyone holding ``<resource>.delete`` (the moderator's grant)."""
    action = "update" if note.author_id == user.id else "delete"
    ensure_workspace_permission(user, ws_id, _resource(note.registration_id), action)


def _decode_file(data: dict[str, Any]) -> bytes:
    content_b64 = data.get("content_b64") or ""
    if len(content_b64) > _MAX_B64:
        raise HTTPException(status_code=422, detail=f"File too large (max {notes_module.MAX_ATTACHMENT_SIZE} bytes)")
    try:
        return base64.b64decode(content_b64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="content_b64 is not valid base64") from exc


async def _delete_objects(*, key: str | None = None, prefix: str | None = None) -> None:
    """Best-effort cleanup after the row is gone: a failure leaves an orphan object, logged, not an error."""
    try:
        s3 = await get_s3()
        if key is not None:
            await s3.delete_object(key)
        if prefix is not None:
            await s3.delete_prefix(prefix)
    except Exception:
        _log.exception("registration note attachment cleanup failed (key={}, prefix={})", key, prefix)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.regnote_list")
    async def _regnote_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id, ws_id = await _gate(session, data)
            registration_id = _q1(data, "registration_id", int)
            team_id = _q1(data, "registration_team_id", int)
            if (registration_id is None) == (team_id is None):
                raise HTTPException(
                    status_code=422, detail="exactly one of registration_id / registration_team_id is required"
                )
            ensure_workspace_permission(user, ws_id, _resource(registration_id), "read")
            await notes_service.ensure_target(
                session, tournament_id=tournament_id, registration_id=registration_id, team_id=team_id
            )
            return _dump(
                await notes_service.list_for(
                    session, tournament_id=tournament_id, registration_id=registration_id, team_id=team_id
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_counts")
    async def _regnote_counts(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id, ws_id = await _gate(session, data)
            # Counts reveal nothing but "this row has notes"; either list's read grant is enough.
            if not any(user.has_workspace_permission(ws_id, res, "read") for res in ("registration", "team")):
                raise HTTPException(status_code=403, detail="registration.read or team.read required")
            return _dump(await notes_service.counts(session, tournament_id=tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_create")
    async def _regnote_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id, ws_id = await _gate(session, data)
            body = RegistrationNoteCreate.model_validate(_payload(data) or {})
            ensure_workspace_permission(user, ws_id, _resource(body.registration_id), "update")
            return _dump(
                await notes_service.create(
                    session,
                    tournament_id=tournament_id,
                    registration_id=body.registration_id,
                    team_id=body.registration_team_id,
                    author_id=user.id,
                    body=body.body,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_update")
    async def _regnote_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, _ws_id, note = await _note_gate(session, data, "update")
            _ensure_author(user, note)
            body = RegistrationNoteUpdate.model_validate(_payload(data) or {})
            return _dump(await notes_service.update_body(session, note=note, body=body.body))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_delete")
    async def _regnote_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, ws_id, note = await _note_gate(session, data, None)
            _ensure_may_delete(user, ws_id, note)
            prefix = await notes_service.delete(session, note=note)
            await _delete_objects(prefix=prefix)
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_attachment_upload")
    async def _regnote_attachment_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, _ws_id, note = await _note_gate(session, data, "update")
            _ensure_author(user, note)
            file_data = _decode_file(data)
            filename, extension, content_type = notes_module.resolve_upload(
                str(data.get("filename") or ""), len(file_data)
            )
            key = notes_service.new_attachment_key(note, extension)
            tournament_id, note_id = note.tournament_id, note.id
            # No transaction stays open across the S3 round trip.
            await session.commit()
            s3 = await get_s3()
            if not await s3.put_object(key, file_data, content_type, public=False):
                raise HTTPException(status_code=502, detail="File upload failed")
            try:
                return _dump(
                    await notes_service.add_attachment(
                        session,
                        note_id=note_id,
                        tournament_id=tournament_id,
                        key=key,
                        filename=filename,
                        content_type=content_type,
                        size=len(file_data),
                        uploaded_by=user.id,
                    )
                )
            except Exception:
                await _delete_objects(key=key)
                raise

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_attachment_delete")
    async def _regnote_attachment_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, ws_id, note = await _note_gate(session, data, None)
            _ensure_may_delete(user, ws_id, note)
            attachment = notes_service.attachment(note, _path_int(data, "attachment_id"))
            read, key = await notes_service.delete_attachment(session, note=note, attachment=attachment)
            await _delete_objects(key=key)
            return _dump(read)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regnote_attachment_url")
    async def _regnote_attachment_url(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, _ws_id, note = await _note_gate(session, data, "read")
            attachment = notes_service.attachment(note, _path_int(data, "attachment_id"))
            await session.commit()
            url = await (await get_s3()).generate_presigned_url(
                attachment.s3_key,
                _URL_TTL_SECONDS,
                content_disposition=notes_module.content_disposition(attachment),
            )
            return _dump(RegistrationNoteAttachmentUrl(url=url))

        return await _run(logger, op)
