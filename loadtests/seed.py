"""One-shot data seeding for the locust scenarios.

Detail endpoints (`/tournaments/{id}`, `/users/{id}/profile`, ...) need REAL
ids or the run just measures the 404 path. Before the first simulated user
starts, we fetch the public list/lookup endpoints once and build id pools
that every user class samples from.

Seeding is lazy + thread-safe: the first `User.on_start` triggers it, every
other user blocks on the lock until the pools are ready. This works both
standalone and distributed (each worker process seeds itself with ~10 cheap
GETs). Plain `requests` is used so the seeding traffic never pollutes the
locust statistics.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import requests

import config

logger = logging.getLogger("owt.seed")

_lock = threading.Lock()
_seed: "SeedData | None" = None


@dataclass
class SeedData:
    workspace_ids: list[int] = field(default_factory=list)
    tournament_ids: list[int] = field(default_factory=list)
    user_ids: list[int] = field(default_factory=list)
    user_names: list[str] = field(default_factory=list)
    hero_ids: list[int] = field(default_factory=list)
    map_ids: list[int] = field(default_factory=list)
    gamemode_ids: list[int] = field(default_factory=list)
    match_ids: list[int] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    encounter_ids: list[int] = field(default_factory=list)
    algorithm_ids: list[int] = field(default_factory=list)

    @property
    def workspace_id(self) -> int | None:
        if config.WORKSPACE_ID is not None:
            return config.WORKSPACE_ID
        return self.workspace_ids[0] if self.workspace_ids else None


def _extract_items(payload: Any) -> list[dict]:
    """Accept both plain lists and `Paginated` envelopes ({.., results: [..]})."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _ids(payload: Any, key: str = "id") -> list[int]:
    out: list[int] = []
    for item in _extract_items(payload):
        value = item.get(key)
        if isinstance(value, int):
            out.append(value)
    return out[: config.SEED_POOL_SIZE]


def _names(payload: Any, key: str = "name") -> list[str]:
    out: list[str] = []
    for item in _extract_items(payload):
        value = item.get(key)
        if isinstance(value, str) and value:
            out.append(value)
    return out[: config.SEED_POOL_SIZE]


def _get(session: requests.Session, host: str, path: str, params: dict | None = None) -> Any:
    try:
        resp = session.get(f"{host}{path}", params=params, timeout=config.SEED_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("seed request %s failed: %s", path, exc)
        return None
    if resp.status_code != 200:
        logger.warning("seed request %s -> HTTP %s", path, resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError:
        logger.warning("seed request %s returned non-JSON body", path)
        return None


def _load(host: str) -> SeedData:
    session = requests.Session()
    if config.AUTH_TOKEN:
        session.headers["Authorization"] = f"Bearer {config.AUTH_TOKEN}"

    seed = SeedData()
    seed.workspace_ids = _ids(_get(session, host, "/api/v1/workspaces"))

    ws: dict[str, int] = {}
    if seed.workspace_id is not None:
        ws = {"workspace_id": seed.workspace_id}

    page = {"page": 1, "per_page": config.SEED_POOL_SIZE if config.SEED_POOL_SIZE <= 100 else 100}

    seed.tournament_ids = _ids(_get(session, host, "/api/v1/tournaments/lookup", ws))

    users_payload = _get(session, host, "/api/v1/users", page)
    seed.user_ids = _ids(users_payload)
    seed.user_names = _names(users_payload)

    seed.hero_ids = _ids(_get(session, host, "/api/v1/heroes", page))
    seed.map_ids = _ids(_get(session, host, "/api/v1/maps", page))
    seed.gamemode_ids = _ids(_get(session, host, "/api/v1/gamemodes", page))
    seed.match_ids = _ids(_get(session, host, "/api/v1/matches", {**page, **ws}))
    seed.team_ids = _ids(_get(session, host, "/api/v1/teams", {**page, **ws}))
    seed.encounter_ids = _ids(_get(session, host, "/api/v1/encounters", {**page, **ws}))
    seed.algorithm_ids = _ids(_get(session, host, "/api/analytics/algorithms", {"page": 1, "per_page": 50}))

    logger.info(
        "seeded pools: workspaces=%d tournaments=%d users=%d heroes=%d maps=%d "
        "gamemodes=%d matches=%d teams=%d encounters=%d algorithms=%d",
        len(seed.workspace_ids),
        len(seed.tournament_ids),
        len(seed.user_ids),
        len(seed.hero_ids),
        len(seed.map_ids),
        len(seed.gamemode_ids),
        len(seed.match_ids),
        len(seed.team_ids),
        len(seed.encounter_ids),
        len(seed.algorithm_ids),
    )
    if not any((seed.tournament_ids, seed.user_ids, seed.hero_ids)):
        logger.warning(
            "all id pools are empty — is the stack up and the database populated? detail-endpoint tasks will be skipped"
        )
    return seed


def ensure_seeded(host: str) -> SeedData:
    """Return the shared pools, loading them exactly once per process."""
    global _seed
    if _seed is not None:
        return _seed
    with _lock:
        if _seed is None:
            _seed = _load(host.rstrip("/"))
    return _seed
