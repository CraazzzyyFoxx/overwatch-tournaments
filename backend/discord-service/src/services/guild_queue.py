"""One sequential queue of Discord calls per guild, served by priority.

Discord rate-limits per guild and publishes neither the move nor the create limits, so the bot stops
guessing: every voice call of one guild goes through one worker, one at a time. discord.py waits out a
429 inside the call; what this adds is the ORDER when calls pile up -- a member joining the hub must
not wait behind a batch of channel creates, and a channel delete waits behind everything.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import Any

__all__ = ("GuildQueues", "Priority")


class Priority(IntEnum):
    """Lower runs first; calls of equal priority run in the order they were submitted."""

    HUB_MOVE = 0  # also the mix moves
    ROUND_MOVE = 1
    STRUCTURE = 2  # create / edit / permissions
    DELETE = 3


class _Lane:
    __slots__ = ("heap", "task")

    def __init__(self) -> None:
        self.heap: list[tuple[int, int, Callable[[], Awaitable[Any]], asyncio.Future[Any]]] = []
        self.task: asyncio.Task[None] | None = None


class GuildQueues:
    def __init__(self) -> None:
        self._lanes: dict[int, _Lane] = {}
        self._seq = itertools.count()

    def submit[T](self, guild_id: int, priority: Priority, work: Callable[[], Awaitable[T]]) -> asyncio.Future[T]:
        """Queue ``work``; the future carries its result, or the exception it raised.

        Not a coroutine on purpose: enqueueing is immediate, so a caller that submits a list in order
        gets that order inside one priority however it later awaits the futures.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        lane = self._lanes.get(guild_id)
        if lane is None:
            lane = self._lanes[guild_id] = _Lane()
            lane.task = loop.create_task(self._serve(guild_id, lane))
        heapq.heappush(lane.heap, (int(priority), next(self._seq), work, future))
        return future

    async def _serve(self, guild_id: int, lane: _Lane) -> None:
        try:
            while lane.heap:
                _, _, work, future = heapq.heappop(lane.heap)
                if future.cancelled():  # its submitter gave up while it waited
                    continue
                try:
                    result = await work()
                except asyncio.CancelledError:
                    future.cancel()
                    raise
                except Exception as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
        finally:
            # No await between the emptiness check and here: a submit cannot slip into a dead lane.
            del self._lanes[guild_id]

    def close(self) -> None:
        for lane in list(self._lanes.values()):
            if lane.task is not None:
                lane.task.cancel()
            for _, _, _, future in lane.heap:
                future.cancel()
            lane.heap.clear()
