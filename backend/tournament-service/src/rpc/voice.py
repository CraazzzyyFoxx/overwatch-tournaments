"""Tournament voice channels over RPC (``docs/tournament-voice-channels.md``).

``rpc.tournament.voice_plan`` is internal (discord-service, no identity, no gateway route); the three admin
subjects behind ``/admin/tournaments/{id}/voice`` check the tournament's workspace permission.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from shared.services.discord_client import DiscordClient
from src.core import auth
from src.rpc._helpers import _identity, _payload, _read, _require_id
from src.schemas import voice as voice_schemas
from src.services.voice import admin as voice_admin
from src.services.voice.plan import build_voice_plan


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.voice_plan")
    async def _voice_plan(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            try:
                tournament_id = int(data["tournament_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="tournament_id is required"
                ) from exc
            return await build_voice_plan(session, tournament_id)

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.voice_get")
    async def _voice_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ensure_workspace_permission(
                user, await auth.get_tournament_workspace_id(session, tournament_id), "tournament", "read"
            )
            return await voice_admin.status_of(session, tournament_id)

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.voice_put")
    async def _voice_put(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = voice_schemas.VoiceSettings.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="tournament.voice.update",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after=body.model_dump(mode="json"),
            )
            discord = DiscordClient(broker=broker)
            return await voice_admin.save_settings(
                session, tournament_id, body, list_channels=discord.guild_channels, list_roles=discord.guild_roles
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.voice_sync")
    async def _voice_sync(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ensure_workspace_permission(
                user, await auth.get_tournament_workspace_id(session, tournament_id), "tournament", "update"
            )
            return await voice_admin.request_sync(session, tournament_id)

        return await _read(logger, op)
