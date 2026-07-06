#!/usr/bin/env python3
"""Byte-parity check: app-worker (typed RPC behind the gateway) vs the HTTP backend.

Run this BEFORE decommissioning the HTTP ``backend`` service. It hits every public
GET on ``/api/v1/core/*`` through both the gateway (RPC path) and the HTTP
app-service directly, and diffs HTTP status + content-type + canonicalised JSON
(``json.dumps(sort_keys=True)``). Detail-endpoint ids are discovered from the list
endpoints so the script adapts to whatever data the target DB has.

Usage (from inside the docker network, e.g. `docker compose exec gateway` is Go —
run it from a python container or the host with both ports reachable):

    GATEWAY_BASE=http://gateway:8080 HTTP_BASE=http://backend:8000 \
        WORKSPACE_ID=1 python app_parity_check.py

Both bases are hit at the SAME external path (``/api/v1/core/...``); the HTTP
service serves it via its ``root_path`` exactly as the gateway proxy did. Error
bodies are NOT compared byte-for-byte (the gateway flattens ``{detail: "..."}``
while the HTTP service may return a list) — only status + content-type for non-2xx.

Exit code is non-zero if any endpoint mismatches.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

GATEWAY = os.environ.get("GATEWAY_BASE", "http://gateway:8080").rstrip("/")
HTTP = os.environ.get("HTTP_BASE", "http://backend:8000").rstrip("/")
WS = os.environ.get("WORKSPACE_ID")  # optional; appended as ?workspace_id= where relevant
PREFIX = "/api/v1/core"


def _ws(params: dict[str, Any] | None = None) -> dict[str, Any]:
    p = dict(params or {})
    if WS:
        p.setdefault("workspace_id", WS)
    return p


def _canon(body: bytes) -> str:
    try:
        return json.dumps(json.loads(body), sort_keys=True, ensure_ascii=False)
    except Exception:
        return body.decode("utf-8", "replace")


def _first_id(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> int | None:
    try:
        r = client.get(GATEWAY + path, params=params, timeout=30)
        data = r.json()
    except Exception:
        return None
    rows = data.get("results") if isinstance(data, dict) else data
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict) and "id" in first:
            return int(first["id"])
    return None


def build_paths(client: httpx.Client) -> list[tuple[str, dict[str, Any]]]:
    """Return (path, params) pairs to diff. Detail ids discovered from lists."""
    out: list[tuple[str, dict[str, Any]]] = []

    def add(path: str, params: dict[str, Any] | None = None) -> None:
        out.append((path, params or {}))

    # Lookups + lists
    for ent in ("heroes", "maps", "gamemodes"):
        add(f"{PREFIX}/{ent}/lookup")
        add(f"{PREFIX}/{ent}", {"page": 1, "per_page": 5})
    add(f"{PREFIX}/achievements", _ws({"page": 1, "per_page": 5}))
    add(f"{PREFIX}/workspaces")
    add(f"{PREFIX}/users", {"page": 1, "per_page": 5})
    add(f"{PREFIX}/users/search", {"query": "a"})
    add(f"{PREFIX}/users/overview", _ws({"page": 1, "per_page": 5}))
    add(f"{PREFIX}/users/overview/stats", _ws())
    add(f"{PREFIX}/users/overview/catalog", _ws())
    add(f"{PREFIX}/heroes/statistics/playtime", _ws({"page": 1, "per_page": 5}))
    for stat in ("champion", "winrate", "won-maps"):
        add(f"{PREFIX}/statistics/{stat}", _ws({"page": 1, "per_page": 5}))
    add(f"{PREFIX}/statistics/dashboard", _ws())

    # Detail endpoints (discover ids)
    hero_id = _first_id(client, f"{PREFIX}/heroes", {"per_page": 1})
    map_id = _first_id(client, f"{PREFIX}/maps", {"per_page": 1})
    gm_id = _first_id(client, f"{PREFIX}/gamemodes", {"per_page": 1})
    ach_id = _first_id(client, f"{PREFIX}/achievements", _ws({"per_page": 1}))
    user_id = _first_id(client, f"{PREFIX}/users", {"per_page": 1})
    ws_id = _first_id(client, f"{PREFIX}/workspaces")

    if hero_id:
        add(f"{PREFIX}/heroes/{hero_id}")
        add(f"{PREFIX}/heroes/{hero_id}/leaderboard", _ws({"per_page": 5}))
    if map_id:
        add(f"{PREFIX}/maps/{map_id}", {"entities": "gamemode"})
    if gm_id:
        add(f"{PREFIX}/gamemodes/{gm_id}")
    if ach_id:
        add(f"{PREFIX}/achievements/{ach_id}", {"entities": "hero"})
        add(f"{PREFIX}/achievements/{ach_id}/users", {"per_page": 5})
    if ws_id:
        add(f"{PREFIX}/workspaces/{ws_id}")
    if user_id:
        for sub in (
            "profile",
            "tournaments",
            "maps",
            "heroes",
            "teammates",
            "encounters",
            "maps/summary",
            "matches/summary",
        ):
            add(f"{PREFIX}/users/{user_id}/{sub}", _ws())
        add(f"{PREFIX}/achievements/user/{user_id}", _ws())
        add(f"{PREFIX}/users/{user_id}/compare", _ws())
    return out


def main() -> int:
    mismatches = 0
    total = 0
    with httpx.Client() as client:
        for path, params in build_paths(client):
            total += 1
            try:
                g = client.get(GATEWAY + path, params=params, timeout=60)
                h = client.get(HTTP + path, params=params, timeout=60)
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR  {path} :: request failed: {exc}")
                mismatches += 1
                continue

            problems = []
            if g.status_code != h.status_code:
                problems.append(f"status {g.status_code} != {h.status_code}")
            gct = g.headers.get("content-type", "").split(";")[0]
            hct = h.headers.get("content-type", "").split(";")[0]
            if gct != hct:
                problems.append(f"content-type {gct!r} != {hct!r}")
            # Only diff the JSON body for 2xx (error bodies are intentionally
            # flattened on the gateway path).
            if g.status_code < 300 and h.status_code < 300:
                if _canon(g.content) != _canon(h.content):
                    problems.append("body differs")
            if problems:
                mismatches += 1
                print(f"DIFF   {path}?{params} :: {'; '.join(problems)}")
            else:
                print(f"OK     {path}")

    print(f"\n{total - mismatches}/{total} endpoints match.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
