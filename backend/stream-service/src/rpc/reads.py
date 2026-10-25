"""Public read subscribers ``rpc.stream.tournament_streams``, ``rpc.stream.tournament_vods`` and
``rpc.stream.encounter_vods``.

Serve ``GET /api/v1/streams/tournament/{tournament_id}`` — the "who is on air" block
of a tournament page — and the POV VOD chronology at
``GET /api/v1/streams/tournament/{tournament_id}/vods`` and
``GET /api/v1/streams/encounter/{encounter_id}/vods``, for anonymous viewers.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from redis.asyncio import Redis

from shared.services.tournament.visibility import ensure_tournament_viewable
from src.core import db
from src.core.clients import realtime_redis
from src.schemas.stream import StreamVodsRead, TournamentStreamsRead
from src.services.chronology import stream_chronology_reader
from src.services.tournament_streams import tournament_streams_reader

from . import _common as c

__all__ = ("encounter_vods", "register", "tournament_streams", "tournament_vods")


async def tournament_streams(session: Any, redis: Redis, data: dict[str, Any]) -> TournamentStreamsRead:
    """Gate, then read. The order is the contract.

    ``ensure_tournament_viewable`` runs FIRST, before a single stream row or Redis
    key is touched: the gateway caches this response without the viewer in the key
    (``respcache.TTLOnly``), so an ineligible viewer must be rejected before the
    shared cache is consulted. A hidden tournament answers 404, not 403.
    """
    tournament_id = c.require_path_int(data, "tournament_id")
    await ensure_tournament_viewable(session, c.optional_actor(data), tournament_id)
    return await tournament_streams_reader.build(session, redis, tournament_id)


async def tournament_vods(session: Any, data: dict[str, Any]) -> StreamVodsRead:
    """Gate, then read — same contract and same reason as ``tournament_streams``."""
    tournament_id = c.require_path_int(data, "tournament_id")
    await ensure_tournament_viewable(session, c.optional_actor(data), tournament_id)
    return await stream_chronology_reader.build(session, tournament_id)


async def encounter_vods(session: Any, data: dict[str, Any]) -> StreamVodsRead:
    """Resolve the encounter's tournament, gate on it, then read.

    The owner lookup is the only read before the gate, and it reveals nothing a
    404 would not: an unknown encounter answers 404 like a hidden tournament. A
    mix's encounter has no tournament and therefore no POV streams.
    """
    encounter_id = c.require_path_int(data, "encounter_id")
    tournament_id = await stream_chronology_reader.encounter_tournament_id(session, encounter_id)
    if tournament_id is None:
        return StreamVodsRead(vods=[])
    await ensure_tournament_viewable(session, c.optional_actor(data), tournament_id)
    return await stream_chronology_reader.build(session, tournament_id, encounter_id=encounter_id)


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    @broker.subscriber("rpc.stream.tournament_streams")
    async def _tournament_streams(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_streams(session, realtime_redis, data)

        # exclude_none stays OFF (the envelope default): `live: null` MUST appear on
        # the wire, or "no live detection" is indistinguishable from a missing field.
        return await c.envelope(logger, "tournament_streams", op, session_factory=sf)

    @broker.subscriber("rpc.stream.tournament_vods")
    async def _tournament_vods(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_vods(session, data)

        return await c.envelope(logger, "tournament_vods", op, session_factory=sf)

    @broker.subscriber("rpc.stream.encounter_vods")
    async def _encounter_vods(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await encounter_vods(session, data)

        return await c.envelope(logger, "encounter_vods", op, session_factory=sf)
