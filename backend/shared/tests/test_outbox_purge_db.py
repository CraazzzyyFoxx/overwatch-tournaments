"""``purge_outbox`` deletes only published rows past retention, in batches; pending, failed and dead rows stay."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.messaging import outbox
from shared.models.platform.outbox import EventOutbox
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres


class PurgeOutboxTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = f"purge-{os.getpid()}-{id(self)}"

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(EventOutbox).where(EventOutbox.event_id.startswith(self.tag)))
            await s.commit()
        await self.engine.dispose()

    async def _add(self, name: str, status: str, *, age: timedelta, published: bool) -> None:
        at = datetime.now(UTC) - age
        async with self.Session() as s:
            s.add(
                EventOutbox(
                    event_id=f"{self.tag}-{name}",
                    event_type="test",
                    routing_key="test",
                    payload_json={},
                    status=status,
                    attempts=0,
                    created_at=at,
                    next_attempt_at=at,
                    published_at=at if published else None,
                )
            )
            await s.commit()

    async def _left(self) -> list[str]:
        async with self.Session() as s:
            ids = await s.scalars(sa.select(EventOutbox.event_id).where(EventOutbox.event_id.startswith(self.tag)))
            return sorted(event_id.removeprefix(f"{self.tag}-") for event_id in ids)

    async def test_only_published_rows_past_retention_are_deleted_batch_by_batch(self) -> None:
        week = outbox.PUBLISHED_RETENTION
        old = {"status": "published", "age": week + timedelta(days=1), "published": True}
        # Kept rows between the old ones (ids ascend in insert order): each id-ordered batch must walk past them.
        await self._add("old-1", **old)
        await self._add("recent", "published", age=week - timedelta(days=1), published=True)
        await self._add("old-2", **old)
        await self._add("pending", "pending", age=week * 2, published=False)
        await self._add("old-3", **old)
        await self._add("failed", "failed", age=week * 2, published=False)
        await self._add("old-4", **old)
        await self._add("dead", "dead", age=week * 2, published=False)
        await self._add("old-5", **old)

        with patch.object(outbox, "PURGE_BATCH", 2):
            deleted = await outbox.purge_outbox(self.Session)

        self.assertGreaterEqual(deleted, 5)
        self.assertEqual(["dead", "failed", "pending", "recent"], await self._left())
