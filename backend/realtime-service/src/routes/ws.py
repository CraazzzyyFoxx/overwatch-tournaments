from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from shared.models.auth_user import AuthUser
from shared.models.realtime import WorkspaceEvent
from shared.schemas.realtime import SubscribeOp, WorkspaceEventEnvelope
from shared.services.balancer_realtime import BALANCER_PRESENCE
from shared.services.realtime_publisher import event_to_envelope

from src.core import config, db
from src.core.auth import get_websocket_user_optional
from src.protocol import (
    ProtocolError,
    error_frame,
    event_frame,
    parse_client_op,
    pong_frame,
    subscribed_frame,
)
from src.services.connection_manager import (
    ConnectionState,
    connection_manager,
    is_presence_topic,
)
from src.services.event_replay import ReplayGapTooLarge, event_replay_service
from src.services.topic_acl import topic_acl_registry

router = APIRouter()


async def _broadcast_presence(topic: str) -> None:
    """Fan an ephemeral presence frame to everyone subscribed to ``topic``.

    Not persisted (``event_id=0``) so it never advances the replay cursor.
    The payload carries the current connected user ids; the frontend resolves
    them to avatars from the workspace member list.
    """
    envelope = WorkspaceEventEnvelope(
        event_id=0,
        event_type=BALANCER_PRESENCE,
        schema_version=1,
        occurred_at=datetime.now(UTC),
        actor_user_id=None,
        data={"user_ids": connection_manager.presence_user_ids(topic)},
    )
    await connection_manager.route(topic, event_frame(topic, envelope))


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    user = await _resolve_websocket_user(websocket)
    state = await connection_manager.register(websocket, user)
    try:
        while True:
            try:
                raw_frame = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=config.settings.ws_idle_timeout,
                )
            except TimeoutError:
                await websocket.close(code=1001)
                return

            try:
                op = parse_client_op(raw_frame)
            except ProtocolError as exc:
                await connection_manager.send(state, error_frame(exc.code, exc.message, topic=exc.topic))
                continue

            if op.op == "ping":
                await connection_manager.send(state, pong_frame())
                continue

            if op.op == "unsubscribe":
                connection_manager.unsubscribe(state, op.topic)
                if is_presence_topic(op.topic):
                    await _broadcast_presence(op.topic)
                continue

            await _handle_subscribe(state, cast(SubscribeOp, op), user)
    except WebSocketDisconnect:
        return
    finally:
        # Recompute presence for any presence topic this connection was on,
        # after removing it so the leaving user is no longer counted.
        presence_topics = [topic for topic in state.topics if is_presence_topic(topic)]
        connection_manager.cleanup(state)
        for topic in presence_topics:
            await _broadcast_presence(topic)


async def _resolve_websocket_user(websocket: WebSocket) -> AuthUser | None:
    async with db.async_session_maker() as session:
        return await get_websocket_user_optional(websocket, session)


async def _handle_subscribe(state: ConnectionState, op: SubscribeOp, user: AuthUser | None) -> None:
    started = perf_counter()
    replay_error: dict[str, Any] | None = None
    events: list[WorkspaceEvent] = []
    cursor = 0

    async with db.async_session_maker() as session:
        if not await topic_acl_registry.allow(user, op.topic, session):
            replay_error = error_frame(
                "forbidden",
                "You are not allowed to subscribe to this topic",
                topic=op.topic,
            )
        else:
            cursor = await event_replay_service.current_cursor(session, op.topic)
            try:
                events = await event_replay_service.since(
                    session,
                    topic=op.topic,
                    after_event_id=op.after_event_id,
                    up_to_event_id=cursor,
                )
            except ReplayGapTooLarge:
                replay_error = error_frame(
                    "replay_gap_too_large",
                    "Too many missed events; refetch a fresh snapshot before subscribing again",
                    topic=op.topic,
                )

    if replay_error is not None:
        connection_manager.unsubscribe(state, op.topic)
        await connection_manager.send(state, replay_error)
        return

    await connection_manager.subscribe(state, op.topic)
    for event in events:
        await connection_manager.send(state, event_frame(op.topic, event_to_envelope(event)))
    await connection_manager.send(state, subscribed_frame(op.topic, cursor))
    logger.debug(
        "Realtime topic subscribed",
        topic=op.topic,
        after_event_id=op.after_event_id,
        cursor=cursor,
        replay_count=len(events),
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
    if is_presence_topic(op.topic):
        await _broadcast_presence(op.topic)
