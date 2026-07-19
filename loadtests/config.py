"""Environment-driven configuration for the OWT locust suite.

All knobs are plain env vars so the same locustfile works locally
(nginx on http://localhost, APP_PORT=80), against a staging URL, or
inside CI without editing code.
"""

from __future__ import annotations

import os


def _int_or_none(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw.isdigit() else None


#: Pin every workspace-scoped request to one workspace. Unset -> the seeder
#: picks the first workspace returned by GET /api/v1/workspaces.
WORKSPACE_ID: int | None = _int_or_none("OWT_WORKSPACE_ID")

#: Optional access token (the gateway accepts `Authorization: Bearer <jwt>`).
#: Without it every scenario still works — the whole suite targets the
#: public (AuthNone / AuthOptional) read surface.
AUTH_TOKEN: str = os.getenv("OWT_AUTH_TOKEN", "").strip()

#: Timeout (seconds) for the one-shot seeding requests.
SEED_TIMEOUT: float = float(os.getenv("OWT_SEED_TIMEOUT", "30"))

#: Cap for how many ids of each entity the seeder keeps in its pools.
SEED_POOL_SIZE: int = int(os.getenv("OWT_SEED_POOL_SIZE", "100"))
