"""Tournament image upload over a real session and an in-memory bucket.

Two guarantees, both invisible to the stubbed-session suites:

* no transaction is open while S3 is called: under pgBouncer transaction pooling
  an open one pins a server connection idle for the whole round trip;
* the previous file is removed only after the row pointing at the new one has
  committed, so a failed upload or write never leaves the row pointing at a
  deleted object.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import uuid
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.services.ontology import project_disciplines
from shared.testing import create_test_async_engine
from shared.testing.cache import configure_test_cache
from shared.testing.db import ensure_test_postgres
from src.rpc import _helpers as rpc_helpers
from src.rpc import tournament_binary
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PUBLIC = "https://cdn.test/"


class _MemoryS3:
    """A bucket that records, per call, whether the handler's session had a transaction open."""

    def __init__(self, session: AsyncSession, row_url, *, put_ok: bool = True) -> None:
        self._session = session
        self._row_url = row_url
        self._put_ok = put_ok
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, bool]] = []
        self.row_url_at_delete: str | None = None

    async def put_object(self, key, data, content_type="application/octet-stream", *, public=False) -> bool:
        self.calls.append(("put", self._session.in_transaction()))
        if self._put_ok:
            self.objects[key] = data
        return self._put_ok

    def get_public_url(self, key: str) -> str:
        return f"{PUBLIC}{key}"

    async def delete_prefix(self, prefix: str, *, keep: str | None = None) -> int:
        self.calls.append(("delete", self._session.in_transaction()))
        self.row_url_at_delete = await self._row_url()
        doomed = [key for key in self.objects if key.startswith(prefix) and key != keep]
        for key in doomed:
            del self.objects[key]
        return len(doomed)


class TournamentImageUploadTransactions(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        ensure_test_postgres()
        configure_test_cache()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        # The handler commits; keep every commit inside this rollback-only transaction.
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        await project_disciplines(self.session)
        tag = uuid.uuid4().hex
        workspace = models.Workspace(slug=tag, name=tag)
        self.session.add(workspace)
        await self.session.flush()
        tournament = models.Tournament(workspace_id=workspace.id, name=tag, slug=tag)
        self.session.add(tournament)
        await self.session.flush()
        self.tournament_id = tournament.id
        self.old_key = f"avatars/tournaments/{tournament.id}/logo/0ld.png"
        tournament.logo_url = f"{PUBLIC}{self.old_key}"
        await self.session.commit()
        self.identity = make_identity(
            workspaces=[
                {
                    "workspace_id": workspace.id,
                    "rbac_roles": [],
                    "rbac_permissions": [{"resource": "tournament", "action": "update"}],
                }
            ]
        )

    async def asyncTearDown(self):
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _row_url(self) -> str | None:
        # Straight on the connection: never opens a session transaction of its own.
        return await self.connection.scalar(
            sa.select(models.Tournament.logo_url).where(models.Tournament.id == self.tournament_id)
        )

    async def _upload(self, s3: _MemoryS3) -> dict:
        broker = CapturingBroker()
        tournament_binary.register(broker, logger)

        async def get_s3():
            return s3

        async def tournament_read(_session, tournament, _entities):
            # The reply's shape is pinned by test_tournament_image_rpc.py.
            return {"logo_url": tournament.logo_url}

        with (
            patch.object(rpc_helpers.db, "async_session_maker", FakeSessionMaker(self.session)),
            patch.object(tournament_binary, "get_s3", get_s3),
            patch.object(tournament_binary.tournament_flows.flows_service, "tournament_read", tournament_read),
        ):
            return await broker.handlers["rpc.tournament.tournaments.image_upload"](
                {
                    "id": self.tournament_id,
                    "slot": "logo",
                    "identity": self.identity,
                    "content_b64": base64.b64encode(PNG).decode(),
                    "content_type": "image/png",
                },
                None,
            )

    async def test_s3_runs_outside_transactions_and_the_old_file_goes_after_the_commit(self):
        s3 = _MemoryS3(self.session, self._row_url)
        s3.objects[self.old_key] = b"old"

        envelope = await self._upload(s3)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([("put", False), ("delete", False)], s3.calls)
        self.assertNotIn(self.old_key, s3.objects)
        (new_key,) = s3.objects
        # No transaction open and the row already on the new URL: it was committed.
        self.assertEqual(f"{PUBLIC}{new_key}", s3.row_url_at_delete)
        self.assertEqual(f"{PUBLIC}{new_key}", await self._row_url())
        self.assertEqual(f"{PUBLIC}{new_key}", envelope["data"]["logo_url"])

    async def test_failed_upload_leaves_the_old_file_and_the_row(self):
        s3 = _MemoryS3(self.session, self._row_url, put_ok=False)
        s3.objects[self.old_key] = b"old"

        envelope = await self._upload(s3)

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual([("put", False)], s3.calls)
        self.assertEqual({self.old_key: b"old"}, s3.objects)
        self.assertEqual(f"{PUBLIC}{self.old_key}", await self._row_url())
