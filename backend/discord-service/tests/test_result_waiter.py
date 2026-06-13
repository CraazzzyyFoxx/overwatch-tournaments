"""Unit tests for ResultWaiter — the upload→result rendezvous used by the bot.

Replaces the former pg LISTEN/NOTIFY waiter (broken under pgBouncer transaction
pooling). Pure asyncio, so no DB/broker/env is required here.
"""

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.result_waiter import ResultWaiter


class ResultWaiterTests(IsolatedAsyncioTestCase):
    async def test_resolve_done_returns_true(self) -> None:
        waiter = ResultWaiter(timeout=5)
        task = asyncio.create_task(waiter.wait(73, "log.txt"))
        await asyncio.sleep(0)  # let the task register its future
        waiter.resolve(73, "log.txt", True)
        self.assertIs(await task, True)

    async def test_resolve_failed_returns_false(self) -> None:
        waiter = ResultWaiter(timeout=5)
        task = asyncio.create_task(waiter.wait(73, "log.txt"))
        await asyncio.sleep(0)
        waiter.resolve(73, "log.txt", False)
        self.assertIs(await task, False)

    async def test_timeout_returns_none(self) -> None:
        waiter = ResultWaiter(timeout=0.05)
        self.assertIsNone(await waiter.wait(1, "x"))

    async def test_resolve_unknown_key_is_noop(self) -> None:
        waiter = ResultWaiter(timeout=5)
        waiter.resolve(999, "missing", True)  # must not raise

    async def test_resolve_after_timeout_is_noop(self) -> None:
        waiter = ResultWaiter(timeout=0.05)
        self.assertIsNone(await waiter.wait(2, "y"))
        waiter.resolve(2, "y", True)  # future already dropped; must not raise

    async def test_only_matching_key_is_resolved(self) -> None:
        waiter = ResultWaiter(timeout=5)
        task = asyncio.create_task(waiter.wait(10, "a.txt"))
        await asyncio.sleep(0)
        waiter.resolve(10, "b.txt", True)  # different filename — no effect
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        waiter.resolve(10, "a.txt", True)
        self.assertIs(await task, True)
