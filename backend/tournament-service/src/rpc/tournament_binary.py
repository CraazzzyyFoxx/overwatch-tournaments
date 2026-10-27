"""Tournament cover/logo upload/delete over typed RPC (base64 body on the wire).

Same shape as ``src/rpc/team_binary.py`` -- the gateway's multipart ``file``
arrives as ``data["content_b64"]`` + ``data["content_type"]``, the gate is
workspace-scoped (``tournament.update`` on the tournament's workspace), and the
reply is the full ``TournamentRead`` the admin CRUD returns.

Two deliberate differences from the team pair:

* A tournament carries **two** images, so the subjects take a ``slot`` path
  segment (``cover`` | ``logo``). That value ends up inside the S3 key, and this
  handler is the only place it is ever validated -- see ``_slot``.
* The reply is built with ``flows.tournament_read`` and the entity set
  ``AdminRegistryService._ser_tournament`` uses (``registry.TOURNAMENT_ENTITIES``),
  not with ``to_pydantic``:
  ``to_pydantic`` serializes the ``challonge_source``-derived id/slug as ``None``
  unless the caller resolved them, so an upload reply would read back
  "Not linked" and disable the admin form's sync controls (see the comment on
  ``services/admin/registry.py``'s serializer).

Transactions: ``_gate`` commits its read-only lookup before any S3 call, so no
pooled connection sits idle in a transaction across the round trip;
``set_tournament_image`` then writes and commits the row in its own transaction.
Both subjects remove the slot's previous files only after that commit (and after
ending the reply's read transaction): a failed upload or row write leaves the old
image and the row intact, and a failed S3 delete leaves only an orphan object,
never a URL pointing at deleted bytes.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.clients.s3 import delete_old_avatar, upload_avatar
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from src.core import auth
from src.rpc._helpers import _dump, _identity, _require_id, _run
from src.rpc._s3 import decode_image_b64, get_s3
from src.services.admin.registry import TOURNAMENT_ENTITIES
from src.services.admin.tournament import tournament_service
from src.services.tournament import flows as tournament_flows

#: The wide page banner and the square mark. Both are S3 key *segments*.
_SLOTS = frozenset({"cover", "logo"})


def _slot(data: dict[str, Any]) -> str:
    """Validate the ``slot`` path segment before it reaches an S3 key.

    The gateway forwards this straight from the URL, and ``avatar_prefix`` splices
    it into ``avatars/tournaments/{id}/{slot}/`` verbatim, so an unchecked value
    is a caller-chosen prefix (and, on delete, a caller-chosen ``delete_prefix``
    target). Rejecting anything outside the two known slots here is what keeps
    that from being possible at all.
    """
    slot = str(data.get("slot") or "")
    if slot not in _SLOTS:
        raise HTTPException(status_code=400, detail="slot must be one of: cover, logo")
    return slot


async def _gate(session: Any, data: dict[str, Any]) -> tuple[Any, int, str, int]:
    """Rehydrate the identity, resolve the workspace, require tournament.update.

    Returns the actor and the workspace the check ran against so the audit row
    records the same pair the permission gate used, rather than re-resolving it.
    Commits the read-only lookup so no transaction stays open across S3.
    """
    user = _identity(data)
    tournament_id = _require_id(data)
    slot = _slot(data)
    ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
    ensure_workspace_permission(user, ws_id, "tournament", "update")
    await session.commit()
    return user, tournament_id, slot, ws_id


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.tournaments.image_upload")
    async def _image_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id, slot, ws_id = await _gate(session, data)
            s3 = await get_s3()
            result = await upload_avatar(
                s3,
                entity_type="tournaments",
                entity_id=tournament_id,
                file_data=decode_image_b64(data),
                content_type=data.get("content_type", ""),
                variant=slot,
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            # ``set_tournament_image`` commits, so the row goes on the session first.
            # ``_slot`` already narrowed the slot to cover|logo, so the action name
            # it builds can only be one of the two known strings.
            await record_admin_audit(
                session,
                action=f"tournament.{slot}_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"slot": slot, "image_url": result.public_url, "content_type": data.get("content_type")},
            )
            tournament = await tournament_service.set_tournament_image(
                session, tournament_id, slot=slot, url=result.public_url
            )
            reply = _dump(
                await tournament_flows.flows_service.tournament_read(session, tournament, TOURNAMENT_ENTITIES)
            )
            # The row now points at the new key, so the slot's previous files can go
            # -- after ending the reply's read transaction, not inside it.
            await session.commit()
            await delete_old_avatar(
                s3, entity_type="tournaments", entity_id=tournament_id, variant=slot, keep=result.key
            )
            return reply

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.tournaments.image_delete")
    async def _image_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, tournament_id, slot, ws_id = await _gate(session, data)
            await record_admin_audit(
                session,
                action=f"tournament.{slot}_clear",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"slot": slot, "image_url": None},
            )
            tournament = await tournament_service.set_tournament_image(session, tournament_id, slot=slot, url=None)
            reply = _dump(
                await tournament_flows.flows_service.tournament_read(session, tournament, TOURNAMENT_ENTITIES)
            )
            # Same rule as the upload: the bytes go only once the cleared row has
            # committed, and outside the reply's read transaction.
            await session.commit()
            await delete_old_avatar(
                await get_s3(), entity_type="tournaments", entity_id=tournament_id, variant=slot, keep=None
            )
            return reply

        return await _run(logger, op)
