"""Team logo upload/delete over typed RPC (binary body, base64 on the wire).

The gateway's multipart ``file`` arrives as ``data["content_b64"]`` +
``data["content_type"]``, the permission gate is workspace-scoped
(``team.update`` on the workspace resolved from the team's tournament), and the
reply is the same full ``TeamRead`` the generic admin CRUD returns for a team —
so the caller gets ``image_url`` plus the hydrated tournament/roster/captain in
one round trip.

S3 keys live under ``avatars/teams/{team_id}/`` (``upload_avatar`` builds them;
the upload handler removes the previous files once the new URL has committed),
so a re-upload never leaves orphaned objects behind.

Transactions: ``_gate`` commits its read-only lookup before any S3 call, so no
pooled connection sits idle in a transaction across the round trip;
``team_service.set_team_image`` then writes and commits the row in its own
transaction (like every other write in ``services/admin/team.py``). Both
subjects delete objects only after that commit and outside any transaction: a
failed row write leaves the old image intact, and a failed S3 delete leaves only
an orphan object, never an ``image_url`` pointing at deleted bytes.
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
from src.services.admin.registry import TEAM_ENTITIES
from src.services.admin.team import team_service
from src.services.team import flows as team_flows


async def _gate(session: Any, data: dict[str, Any]) -> tuple[Any, int, int]:
    """Rehydrate the identity, resolve the team's workspace, require team.update.

    Returns the actor and the workspace the check ran against so the audit row
    records the same pair the permission gate used, rather than re-resolving it.
    Commits the read-only lookup so no transaction stays open across S3.
    """
    user = _identity(data)
    team_id = _require_id(data)
    ws_id = await auth.get_team_workspace_id(session, team_id)
    ensure_workspace_permission(user, ws_id, "team", "update")
    await session.commit()
    return user, team_id, ws_id


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.teams.image_upload")
    async def _image_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, team_id, ws_id = await _gate(session, data)
            s3 = await get_s3()
            result = await upload_avatar(
                s3,
                entity_type="teams",
                entity_id=team_id,
                file_data=decode_image_b64(data),
                content_type=data.get("content_type", ""),
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            # ``set_team_image`` commits, so the row goes on the session first.
            await record_admin_audit(
                session,
                action="team.image_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="team",
                entity_id=team_id,
                after={"image_url": result.public_url, "content_type": data.get("content_type")},
            )
            team = await team_service.set_team_image(session, team_id, result.public_url)
            reply = _dump(await team_flows.flows_service.to_pydantic(session, team, TEAM_ENTITIES))
            # The row now points at the new key, so the previous files can go --
            # after ending the reply's read transaction, not inside it.
            await session.commit()
            await delete_old_avatar(s3, entity_type="teams", entity_id=team_id, keep=result.key)
            return reply

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.teams.image_delete")
    async def _image_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, team_id, ws_id = await _gate(session, data)
            await record_admin_audit(
                session,
                action="team.image_clear",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="team",
                entity_id=team_id,
                after={"image_url": None},
            )
            team = await team_service.set_team_image(session, team_id, None)
            reply = _dump(await team_flows.flows_service.to_pydantic(session, team, TEAM_ENTITIES))
            # Same rule as the upload: the bytes go only once the cleared row has
            # committed, and outside the reply's read transaction.
            await session.commit()
            await delete_old_avatar(await get_s3(), entity_type="teams", entity_id=team_id, keep=None)
            return reply

        return await _run(logger, op)
