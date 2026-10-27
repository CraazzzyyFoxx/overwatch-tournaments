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

#: Discipline whose catalog (characters, maps, modes) the seeder and the metadata task read.
CATALOG_DISCIPLINE: str = os.getenv("OWT_CATALOG_DISCIPLINE", "overwatch")

# -- draft room scenario (draft_locustfile.py) ------------------------------

#: The room the scenario plays: ids and every seat's token, written by
#: `draft_seed.py`. Holds live tokens, so it is gitignored.
DRAFT_ROOM: str = os.getenv("OWT_DRAFT_ROOM", ".draft-room.json")

#: Seconds between the driver's autopicks — the event rate the room reacts to.
DRAFT_PICK_INTERVAL: float = float(os.getenv("OWT_DRAFT_PICK_INTERVAL", "10"))

#: After this many picks the driver rolls the last one back (every client
#: re-reads the board) and resumes. Unset: no rollback.
DRAFT_ROLLBACK_AFTER: int | None = _int_or_none("OWT_DRAFT_ROLLBACK_AFTER")

#: Seconds between one captain's chat messages (0: the room stays silent).
DRAFT_CHAT_EVERY: float = float(os.getenv("OWT_DRAFT_CHAT_EVERY", "60"))

#: `Origin` of the simulated tabs; the gateway refuses a socket from an origin
#: outside GATEWAY_WS_ALLOWED_ORIGINS. Defaults to the target host.
DRAFT_ORIGIN: str = os.getenv("OWT_DRAFT_ORIGIN", "").strip()
