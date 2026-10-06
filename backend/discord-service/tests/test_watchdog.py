"""The liveness decision: record a live session, or restart a deaf one.

A gateway session can die while the process stays up, and then nothing is
delivered and nothing exits. The three cases below are the whole contract: a
live session leaves a fresh heartbeat for Docker's probe, a short outage is
ridden out (discord.py reconnects on its own), and a long one ends the process.
The clock and the exit are injected, so the test neither sleeps nor dies.
"""

import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prometheus_client import REGISTRY  # noqa: E402

from src.tools.healthcheck import MAX_AGE_SECONDS, is_alive  # noqa: E402
from src.watchdog import GatewayWatchdog  # noqa: E402


def _bot(*, ready: bool, latency: float = 0.042) -> MagicMock:
    return MagicMock(is_ready=MagicMock(return_value=ready), latency=latency)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class WatchdogTests(TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.heartbeat = Path(self._dir.name) / "discord-worker.alive"
        self.clock = _Clock()
        self.exits: list[int] = []

    def _watchdog(self, bot: MagicMock, *, unready_timeout: float = 300.0) -> GatewayWatchdog:
        return GatewayWatchdog(
            bot,
            heartbeat_path=str(self.heartbeat),
            unready_timeout=unready_timeout,
            now=self.clock,
            exit_process=self.exits.append,
        )

    def test_a_live_session_leaves_a_heartbeat_and_its_latency(self) -> None:
        self._watchdog(_bot(ready=True, latency=0.042)).check()

        self.assertTrue(self.heartbeat.exists())
        self.assertEqual(REGISTRY.get_sample_value("discord_gateway_ready"), 1)
        self.assertAlmostEqual(REGISTRY.get_sample_value("discord_gateway_latency_seconds"), 0.042)
        self.assertEqual(self.exits, [])

    def test_a_ready_client_without_a_heartbeat_round_trip_is_not_proof(self) -> None:
        """``latency`` is NaN until the first gateway heartbeat answers."""
        self._watchdog(_bot(ready=True, latency=float("nan"))).check()

        self.assertFalse(self.heartbeat.exists())
        self.assertEqual(REGISTRY.get_sample_value("discord_gateway_ready"), 0)

    def test_a_short_outage_is_ridden_out(self) -> None:
        """discord.py reconnects by itself; restarting on every blip would be worse."""
        watchdog = self._watchdog(_bot(ready=True))
        watchdog.check()
        self.heartbeat.unlink()

        watchdog._bot = _bot(ready=False)
        self.clock.now += 120.0
        watchdog.check()

        self.assertEqual(self.exits, [])
        # Nothing was recorded either: a stale heartbeat is what the probe reads.
        self.assertFalse(self.heartbeat.exists())

    def test_an_outage_past_the_threshold_ends_the_process(self) -> None:
        watchdog = self._watchdog(_bot(ready=False), unready_timeout=300.0)

        self.clock.now += 299.0
        watchdog.check()
        self.assertEqual(self.exits, [])

        self.clock.now += 2.0
        watchdog.check()
        self.assertEqual(self.exits, [1])

    def test_the_clock_restarts_from_the_last_live_tick(self) -> None:
        """A session that recovered must not be killed by the outage before it."""
        watchdog = self._watchdog(_bot(ready=False), unready_timeout=300.0)
        self.clock.now += 290.0
        watchdog.check()

        watchdog._bot = _bot(ready=True)
        watchdog.check()
        watchdog._bot = _bot(ready=False)
        self.clock.now += 290.0
        watchdog.check()

        self.assertEqual(self.exits, [])


class HealthcheckTests(TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.heartbeat = Path(self._dir.name) / "discord-worker.alive"

    def test_a_fresh_heartbeat_passes_and_a_stale_one_fails(self) -> None:
        self.heartbeat.touch()
        now = time.time()

        self.assertTrue(is_alive(self.heartbeat, now=now))
        self.assertTrue(is_alive(self.heartbeat, now=now + MAX_AGE_SECONDS - 1))
        self.assertFalse(is_alive(self.heartbeat, now=now + MAX_AGE_SECONDS + 1))

    def test_a_bot_that_never_came_up_has_no_heartbeat_at_all(self) -> None:
        self.assertFalse(is_alive(self.heartbeat))
