"""Throwaway: drive one real invalidation through all three layers on dev.

Imports the service entrypoint so the process is wired exactly like the worker
(``configure_cache`` + ``configure_realtime`` with the service's own
invalidator), then stages an invalidation for a tournament the same way a write
path does - staged realtime row + outbox row, both released by the commit - and
prints what landed.
"""

from __future__ import annotations

import asyncio
import os

import sqlalchemy as sa

import serve  # noqa: F401  # side effect: configures cache + realtime rail
from shared.services.realtime import Resource, Scope, emit, enqueue_invalidation_outbox
from src.core import db

TOURNAMENT_ID = int(os.environ.get("PROBE_TOURNAMENT_ID", "1"))
PROBE_RESOURCES = os.environ.get("PROBE_RESOURCES", "tournament.detail,tournament.standings")


async def main() -> None:
    scope = Scope.tournament(TOURNAMENT_ID)
    resources = [Resource(name) for name in PROBE_RESOURCES.split(",")]
    async with db.async_session_maker() as session:
        await emit(session, scope=scope, invalidates=resources)
        await enqueue_invalidation_outbox(session, scope=scope, resources=resources)
        await session.commit()
    # Publication is a fire-and-forget task scheduled from after_commit; a
    # one-shot script must not exit before the loop runs it (a worker never does).
    await asyncio.sleep(2)

    async with db.async_session_maker() as session:
        realtime_row = (
            await session.execute(
                sa.text(
                    "SELECT id, topic, event_type, payload::text "
                    "FROM realtime.workspace_event ORDER BY id DESC LIMIT 1"
                )
            )
        ).first()
        outbox_row = (
            await session.execute(
                sa.text(
                    "SELECT exchange, routing_key, status, payload_json::text "
                    "FROM event_outbox ORDER BY id DESC LIMIT 1"
                )
            )
        ).first()

    print("realtime_row:", realtime_row)
    print("outbox_row:", outbox_row)


asyncio.run(main())
