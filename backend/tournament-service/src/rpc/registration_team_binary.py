"""Registration-team crest upload/delete over typed RPC (base64 on the wire).

Structurally the twin of ``src/rpc/team_binary.py`` — same multipart-to-base64
transport, same row-first delete ordering — but a separate module because it
serves a different domain behind a different gate:

* ``team_binary`` writes ``Team.image_url``, the *materialized* tournament team,
  and gates on ``team.update`` in the team's workspace (organizer staff).
* this module writes ``RegistrationTeam.image_url``, the *pre-formation*
  registered team, and gates on being that team's captain — a competitor who
  usually holds no workspace membership at all. The gate runs twice, exactly as
  ``team_binary``'s does: once here before any S3 call (``assert_may_edit_team``,
  lock-free), then authoritatively under the row lock inside ``set_team_image``.

S3 keys live under ``avatars/registration_teams/{team_id}/`` (``upload_avatar``
builds them; the upload handler removes the previous files once the new URL has
committed), so a re-upload never leaves orphaned objects behind — and the prefix
is disjoint from ``avatars/teams/`` even when a registration team and its
exported ``Team`` share an id.

Transport: the gateway sends the path id as ``data["team_id"]`` (matching the
sibling ``regteam_*`` subjects in ``public_rpc.py``, not ``team_binary``'s
``data["id"]``), the multipart file as ``data["content_b64"]`` +
``data["content_type"]``. The reply is the full ``RegistrationTeamRead`` the
captain's own view expects — image plus live occupancy and outstanding invites —
so the UI needs no follow-up read.

Transactions: ``_gate`` commits its read-only check before any S3 call, so no
pooled connection sits idle in a transaction across the round trip;
``set_team_image`` then writes and commits the row in its own transaction, like
every other write in ``services/registration/teams.py``. Both subjects delete
objects only after that commit and outside any transaction: a refused or failed
row write leaves the crest intact, and a failed S3 delete leaves only an orphan
object, never an ``image_url`` pointing at deleted bytes.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.clients.s3 import delete_old_avatar, upload_avatar
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.audit import record_admin_audit
from src.rpc._helpers import _dump, _identity, _path_int, _run
from src.rpc._s3 import decode_image_b64, get_s3
from src.services.registration import teams as team_service


def register(broker: Any, logger: Any) -> None:
    async def _gate(session: Any, data: dict[str, Any]) -> tuple[Any, int]:
        """Rehydrate the identity and refuse a non-captain before any S3 call.

        Without it a stranger's upload would still write an object, orphaned once
        ``set_team_image`` refuses under the row lock; a delete only reaches S3
        after that authoritative check has committed the cleared row. Commits the
        read-only check so no transaction stays open across S3.
        """
        user = _identity(data)
        team_id = _path_int(data, "team_id")
        await team_service.teams_service.assert_may_edit_team(session, team_id=team_id, auth_user=user)
        await session.commit()
        return user, team_id

    @broker.subscriber("rpc.tournament.regteam_image_upload")
    async def _image_upload(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, team_id = await _gate(session, data)
            s3 = await get_s3()
            result = await upload_avatar(
                s3,
                entity_type="registration_teams",
                entity_id=team_id,
                file_data=decode_image_b64(data),
                content_type=data.get("content_type", ""),
            )
            if not result.success:
                raise HTTPException(status_code=400, detail=result.error)
            # ``set_team_image`` commits, so the row goes on the session first.
            # No workspace: the gate is captaincy, not a workspace permission.
            await record_admin_audit(
                session,
                action="registration_team.image_set",
                actor=user,
                data=data,
                workspace_id=None,
                entity_type="registration_team",
                entity_id=team_id,
                after={"image_url": result.public_url, "content_type": data.get("content_type")},
            )
            team = await team_service.teams_service.set_team_image(
                session,
                team_id=team_id,
                auth_user=user,
                image_url=result.public_url,
            )
            # The captain is the only caller, so their own offers are theirs to
            # see — same shape regteam_create returns.
            reply = _dump(await team_service.teams_service.describe_team(session, team, include_invites=True))
            # The row now points at the new key, so the previous files can go --
            # after ending the reply's read transaction, not inside it.
            await session.commit()
            await delete_old_avatar(s3, entity_type="registration_teams", entity_id=team_id, keep=result.key)
            return reply

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_image_delete")
    async def _image_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, team_id = await _gate(session, data)
            await record_admin_audit(
                session,
                action="registration_team.image_clear",
                actor=user,
                data=data,
                workspace_id=None,
                entity_type="registration_team",
                entity_id=team_id,
                after={"image_url": None},
            )
            team = await team_service.teams_service.set_team_image(
                session,
                team_id=team_id,
                auth_user=user,
                image_url=None,
            )
            reply = _dump(await team_service.teams_service.describe_team(session, team, include_invites=True))
            # Same rule as the upload: the bytes go only once the cleared row has
            # committed, and outside the reply's read transaction.
            await session.commit()
            await delete_old_avatar(await get_s3(), entity_type="registration_teams", entity_id=team_id, keep=None)
            return reply

        return await _run(logger, op)
