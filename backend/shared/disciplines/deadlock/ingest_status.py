"""Whether a player's own client (deadlock-api-ingest) uploads their matches: ``GET /v1/players/{id}/ingest-status``.

deadlock-api calls that endpoint internal to its own site, so its contract may change: any answer that is not a
well-formed 200 is "unknown" (``None``), never "inactive".
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime

import httpx

from shared.clients import CircuitBreakerOpen
from shared.clients.http_client import ResilientHttpClient
from shared.disciplines.deadlock.client import deadlock_client
from shared.disciplines.lobby import IngestStatus

__all__ = ("ingest_status",)

#: A mix has at most a few dozen seats; this bounds the burst, not the answer.
_CONCURRENCY = 8


async def _one(http: ResilientHttpClient, gate: asyncio.Semaphore, account_id: str) -> IngestStatus | None:
    if not account_id.isdigit():
        return None
    try:
        async with gate:
            response = await http.get(f"/v1/players/{account_id}/ingest-status")
        if response.status_code != 200:
            return None
        body = response.json()
        uploaded = body.get("last_upload_at")
        return IngestStatus(
            active=bool(body["active"]),
            last_upload_at=datetime.fromisoformat(uploaded) if uploaded else None,
            window_days=int(body.get("window_days") or 14),
        )
    except httpx.HTTPError, CircuitBreakerOpen, ValueError, TypeError, KeyError, AttributeError:
        return None


async def ingest_status(account_ids: Sequence[str]) -> dict[str, IngestStatus | None]:
    ids = list(dict.fromkeys(account_ids))
    if not ids:
        return {}
    gate = asyncio.Semaphore(_CONCURRENCY)
    async with deadlock_client(timeout=5.0, max_retries=1) as http:
        return dict(zip(ids, await asyncio.gather(*(_one(http, gate, account_id) for account_id in ids)), strict=True))
