"""A "Sync now" while another sync of the same feed holds its lock answers 409, against PostgreSQL.

The service reports ``locked`` with zero counts; the RPC used to pass that on as a success with ``total: 0``,
which reads as an empty sheet or a broken mapping.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

from shared.models.platform.audit import AuditLog
from shared.models.registration.registration import RegistrationGoogleSheetFeed
from shared.testing import real_db_sessionmaker
from src.rpc import _helpers as rpc_helpers
from src.rpc import integrations
from tests._rpc_fakes import CapturingBroker, make_identity
from tests.test_registration_sheet_sync_changes import _drop, _registration_count, _seed, _serve


def test_sync_now_on_a_feed_another_sync_holds_is_a_conflict(monkeypatch) -> None:
    async def _run() -> None:
        broker = CapturingBroker()
        integrations.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        handler = broker.handlers["rpc.tournament.sheet_sync"]

        async with real_db_sessionmaker() as Session:
            async with Session() as session:
                seeded = await _seed(session)
                feed_id = await session.scalar(
                    sa.select(RegistrationGoogleSheetFeed.id).where(
                        RegistrationGoogleSheetFeed.tournament_id == seeded["tournament_id"]
                    )
                )
            _serve(monkeypatch, [[seeded["tags"][0], "Support", "a note"]])
            identity = make_identity(
                workspaces=[
                    {
                        "workspace_id": seeded["workspace_id"],
                        "rbac_roles": [],
                        "rbac_permissions": [{"resource": "team", "action": "create"}],
                    }
                ]
            )

            async with Session() as holder:
                # The scheduler's sync of this feed, mid-apply: it holds the feed's lock until it commits.
                await holder.execute(
                    sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext("registration.sheet_sync"), feed_id))
                )
                with (
                    patch.object(rpc_helpers.db, "async_session_maker", Session),
                    patch.object(integrations, "quota", SimpleNamespace(charge=AsyncMock())),
                ):
                    envelope: dict[str, Any] = await asyncio.wait_for(
                        handler({"identity": identity, "id": seeded["tournament_id"]}, None), timeout=30
                    )
                await holder.rollback()

            assert not envelope["ok"], envelope
            assert envelope["error"]["code"] == "conflict"
            async with Session() as session:
                assert await _registration_count(session, seeded["tournament_id"]) == 0
                await session.execute(
                    sa.delete(AuditLog).where(
                        AuditLog.action == "registration.sheet_sync",
                        AuditLog.entity_id == seeded["tournament_id"],
                    )
                )
                await _drop(session, seeded)

    asyncio.run(_run())
