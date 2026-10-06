"""Proof that the gateway session is alive, and a restart when it is not.

The bot serves no port, so nothing outside the process can see whether its
Discord WebSocket still carries events. A gateway session can also die *without*
the process dying: discord.py reconnects on its own, and when that loop stops
making progress the container keeps running, keeps answering a trivial
healthcheck, and quietly stops delivering every card, DM and ``/mix`` answer.
``restart: always`` never fires, because nothing exited.

This loop closes that gap from the inside. Every tick it either

* records a live session -- a heartbeat file whose mtime Docker's healthcheck
  reads (``python -m src.tools.healthcheck``) and two Prometheus gauges, or
* counts how long the session has been down and, past the threshold, logs and
  kills the process so Docker restarts it with a fresh session.

The gauges are plain module-level ``prometheus_client`` metrics, exactly like
``shared.observability.worker``'s: the metrics server main.py already starts
exports them with no further wiring.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from pathlib import Path

import discord
from discord.ext import tasks
from loguru import logger
from prometheus_client import Gauge

__all__ = ("DISCORD_GATEWAY_LATENCY_SECONDS", "DISCORD_GATEWAY_READY", "WATCHDOG_INTERVAL_SECONDS", "GatewayWatchdog")

#: How often the session is checked. Short enough that the heartbeat file is
#: always much younger than the healthcheck's freshness window, long enough to
#: cost nothing: one attribute read and one ``utime`` per tick.
WATCHDOG_INTERVAL_SECONDS = 30.0

DISCORD_GATEWAY_READY = Gauge(
    "discord_gateway_ready",
    "1 while the bot holds a usable Discord gateway session, 0 while it does not.",
)
DISCORD_GATEWAY_LATENCY_SECONDS = Gauge(
    "discord_gateway_latency_seconds",
    "Heartbeat round-trip of the Discord gateway session, in seconds.",
)


class GatewayWatchdog:
    """Touches the heartbeat file while the session is up; exits when it is not.

    ``now`` and ``exit_process`` are injected so the decision can be tested
    without sleeping or dying.
    """

    def __init__(
        self,
        bot: discord.Client,
        *,
        heartbeat_path: str,
        unready_timeout: float,
        now: Callable[[], float] = time.monotonic,
        exit_process: Callable[[int], None] = os._exit,
    ) -> None:
        self._bot = bot
        self._heartbeat = Path(heartbeat_path)
        self._unready_timeout = unready_timeout
        self._now = now
        self._exit = exit_process
        # Startup counts as "down since now": a bot that never finishes its
        # first connect is exactly the case the threshold is there for.
        self._ready_at = now()
        self._loop = tasks.loop(seconds=WATCHDOG_INTERVAL_SECONDS)(self._tick)

    def start(self) -> None:
        self._loop.start()

    def stop(self) -> None:
        self._loop.cancel()

    async def _tick(self) -> None:
        self.check()

    def check(self) -> None:
        """One decision: alive and recorded, or down and (eventually) fatal."""
        latency = self._bot.latency
        # ``latency`` is NaN until the first heartbeat round-trip completes, so a
        # client that is "ready" but has not yet exchanged one is not yet proof.
        ready = self._bot.is_ready() and math.isfinite(latency)
        DISCORD_GATEWAY_READY.set(1 if ready else 0)

        if ready:
            DISCORD_GATEWAY_LATENCY_SECONDS.set(latency)
            self._ready_at = self._now()
            self._touch()
            return

        down_for = self._now() - self._ready_at
        if down_for < self._unready_timeout:
            logger.warning(f"⚠️ Discord gateway session is not ready ({down_for:.0f}s)")
            return

        logger.error(f"❌ Discord gateway session has been down for {down_for:.0f}s; exiting so the container restarts")
        # os._exit, not sys.exit or bot.close(): both of those unwind through the
        # very connection that is already broken -- close() awaits a WebSocket
        # handshake that will not answer, and an exception raised inside a
        # tasks.loop is caught and logged by discord.py rather than ending the
        # process. The watchdog's whole job is to guarantee the exit, and the
        # line above is already written, so nothing worth flushing is lost.
        self._exit(1)

    def _touch(self) -> None:
        try:
            self._heartbeat.touch()
        except OSError as exc:
            # A missing directory or a read-only mount makes the healthcheck
            # fail, which restarts the container -- the error says why.
            logger.error(f"❌ Could not write the heartbeat file {self._heartbeat}: {exc}")
