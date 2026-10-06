"""Docker's liveness probe: ``python -m src.tools.healthcheck``.

Exits 0 while the heartbeat file ``GatewayWatchdog`` touches is fresh, 1 when it
is stale or absent. That file is written only on a tick that saw a live gateway
session, so a stale one means the bot is running but deaf -- which is exactly
the state the old ``python -c "import sys; sys.exit(0)"`` check could not see.

The window is several watchdog intervals wide on purpose: one slow tick (a GC
pause, a busy host) must not restart a healthy bot, while a genuinely dead
session still trips the check within a couple of minutes.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

#: Default for ``Settings.gateway_heartbeat_path``, which imports it from here.
#: The constant lives in the probe rather than the other way round because this
#: module must stay importable with nothing configured: it reads the one
#: variable it needs straight from the environment (in a container, exactly
#: what ``env_file`` puts there) instead of building the service Settings, so a
#: missing ``POSTGRES_HOST`` can never be reported as a dead gateway session.
DEFAULT_HEARTBEAT_PATH = "/tmp/discord-worker.alive"

#: Four watchdog ticks. Docker's own ``retries`` multiplies this further.
MAX_AGE_SECONDS = 120.0


def is_alive(path: Path, *, max_age: float = MAX_AGE_SECONDS, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age


def main() -> int:
    path = Path(os.environ.get("GATEWAY_HEARTBEAT_PATH") or DEFAULT_HEARTBEAT_PATH)
    if is_alive(path):
        return 0
    print(f"discord gateway heartbeat {path} is stale or missing", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
