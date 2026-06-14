from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from shared.services.realtime_topics import REALTIME_CHANNEL_PREFIX

from src.core import config
from src.services.connection_manager import ConnectionManager


class PubSubListener:
    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self._redis = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="realtime-pubsub-listener")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._redis.aclose()

    async def _run(self) -> None:
        while True:
            try:
                async with self._redis.pubsub() as pubsub:
                    await pubsub.psubscribe(f"{REALTIME_CHANNEL_PREFIX}*")
                    async for message in pubsub.listen():
                        if message.get("type") != "pmessage":
                            continue
                        await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Realtime Redis subscriber failed")
                await asyncio.sleep(5)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        channel = str(message.get("channel") or "")
        if not channel.startswith(REALTIME_CHANNEL_PREFIX):
            return
        topic = channel.removeprefix(REALTIME_CHANNEL_PREFIX)

        raw_data = message.get("data")
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode()
        if not isinstance(raw_data, str):
            return

        try:
            frame = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid realtime pubsub payload", topic=topic)
            return

        await self._manager.route(topic, frame)
