"""Typed-RPC handlers for canonical match ingestion (``POST /api/v1/stats/matches`` and its job read).

The gateway relays the original request bytes untouched as ``raw_base64`` next to the trusted ``identity`` it resolved;
nothing in the body can overwrite the identity, and workspace/key come only from the rehydrated credential.

``rpc.stats.ingest.fetch`` and ``rpc.stats.ingest.fetch_list`` are internal: no gateway route reaches them, only
tournament-service, which authorized the caller for the encounter and names the game (``services.ingest.fetch``).
``rpc.stats.ingest.mix_fetch`` / ``mix_fetch_list`` are their pickup-mix twins, routed and authorized here, and
``rpc.stats.ingest.mix_search`` starts a mix round's search by its players again (``services.ingest.search``).
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from faststream.rabbit import RabbitMessage

from shared import quota
from shared.schemas.match_doc import MAX_MATCH_DOC_BYTES
from src.core import clients as _clients
from src.core import db
from src.schemas.ingest import BindIngestRequest
from src.services.ingest import fetch, jobs, search
from src.services.ingest.process import bind_ingest_job, game_observation
from src.services.match_logs.limits import max_base64_length

from . import _common as c

_SF = db.async_session_maker


def _decode(data: dict[str, Any]) -> bytes:
    encoded = data.get("raw_base64")
    if not isinstance(encoded, str):
        raise jobs.IngestRejected(400, "invalid_request", "raw_base64 is required")
    if len(encoded) > max_base64_length(MAX_MATCH_DOC_BYTES):
        raise jobs.IngestRejected(413, "match_document_too_large", "Document exceeds the maximum size")
    try:
        return base64.b64decode(encoded, validate=True)
    except binascii.Error, ValueError:
        raise jobs.IngestRejected(400, "invalid_request", "raw_base64 is not valid base64") from None


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.stats.ingest.submit")
    async def _submit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            principal = jobs.require_ingest_principal(user)
            raw = _decode(data)
            # A submitted document is stored and queued exactly like an admin-uploaded log: the same priced unit.
            await quota.charge(
                user,
                "stats.logs.upload",
                workspace_id=principal.workspace_id,
                size_bytes=len(data["raw_base64"]),
                item_count=1,
            )
            return await jobs.submit_document(session, raw=raw, user=user, s3=_clients.s3_client)

        return await c.envelope(logger, "ingest.submit", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            return await jobs.get_ingest_job(session, job_id=c.require_id(data), user=user)

        return await c.envelope(logger, "ingest.get", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.bind")
    async def _bind(data: dict, msg: RabbitMessage) -> dict:
        # POST /admin/logs/{id}/bind -- admin ``log.update`` in the job's workspace (checked by the service).
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            job_id = c.require_id(data)
            try:
                request = BindIngestRequest.model_validate(c.payload(data))
            except ValueError as exc:
                raise jobs.IngestRejected(422, "invalid_request", "The bind request is invalid") from exc
            return await bind_ingest_job(
                session, job_id=job_id, request=request, user=user, s3=_clients.s3_client, data=data
            )

        return await c.envelope(logger, "ingest.bind", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.game_observation")
    async def _game_observation(data: dict, msg: RabbitMessage) -> dict:
        # GET /admin/logs/games/{id}/observation -- workspace ``log.read`` of the game's workspace.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            return await game_observation(session, encounter_game_id=c.require_id(data), user=user)

        return await c.envelope(logger, "ingest.game_observation", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.fetch")
    async def _fetch(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await fetch.submit_fetch(session, data=c.payload(data), requested_by_user_id=c.actor(data).id)

        return await c.envelope(logger, "ingest.fetch", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.fetch_list")
    async def _fetch_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            body = c.payload(data)
            return await fetch.list_fetches(
                session, encounter_game_id=int(body["encounter_game_id"]), with_warnings=bool(body.get("warnings"))
            )

        return await c.envelope(logger, "ingest.fetch_list", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.mix_fetch")
    async def _mix_fetch(data: dict, msg: RabbitMessage) -> dict:
        # POST /custom-games/{custom_game_id}/matches/{match_id}/match-import -- the mix log upload's audience.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            target = await fetch.mix_round_target(
                session, user, custom_game_id=c.require_id(data), encounter_id=c.require_path_int(data, "match_id")
            )
            return await fetch.submit_fetch(
                session,
                data={**target, "external_id": c.payload(data).get("external_id")},
                requested_by_user_id=user.id,
            )

        return await c.envelope(logger, "ingest.mix_fetch", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.mix_fetch_list")
    async def _mix_fetch_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            target = await fetch.mix_round_target(
                session, user, custom_game_id=c.require_id(data), encounter_id=c.require_path_int(data, "match_id")
            )
            # The host is the mix's organizer: the read carries the warnings.
            return await fetch.list_fetches(session, encounter_game_id=target["encounter_game_id"], with_warnings=True)

        return await c.envelope(logger, "ingest.mix_fetch_list", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.ingest.mix_search")
    async def _mix_search(data: dict, msg: RabbitMessage) -> dict:
        # POST /custom-games/{custom_game_id}/matches/{match_id}/match-search -- the import's audience; 204.
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            target = await fetch.mix_round_target(
                session, user, custom_game_id=c.require_id(data), encounter_id=c.require_path_int(data, "match_id")
            )
            await search.restart_search(session, target)

        return await c.envelope(logger, "ingest.mix_search", op, session_factory=_SF)
