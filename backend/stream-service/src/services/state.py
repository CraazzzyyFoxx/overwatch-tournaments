"""Redis-backed live-stream state for stream-svc.

Everything the poll tick and the RPC reads need that is NOT a Postgres row:

- ``stream:live:{tournament_id}`` — the current live set, one hash field per
  channel, replaced wholesale each tick (see ``services/poller.py`` for why:
  absence means offline, so a partial write would be a lie).
- ``stream:token`` — the cached Helix app access token, shared by every replica.
- ``stream:poll:last_run`` — the tick's due-date cursor.
- ``stream:poll:last_status`` — the last tick's outcome, for the admin health
  panel (``rpc.stream.health``).
- ``stream:poll:history`` — the last ``POLL_HISTORY_LIMIT`` tick outcomes,
  newest first, for the admin task history (``rpc.stream.ticks``).

Wrapped in a class rather than left as free functions taking ``redis`` on every
call: every method here operates on the SAME Redis connection, so binding it
once at construction removes an identical parameter from all nine call sites and
makes the store injectable (a fake in ``StreamPollTick``'s tests, the real
client everywhere else).
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

__all__ = (
    "LAST_RUN_KEY",
    "LAST_RUN_TTL_SECONDS",
    "POLL_HISTORY_KEY",
    "POLL_HISTORY_LIMIT",
    "POLL_STATUS_KEY",
    "POLL_STATUS_TTL_SECONDS",
    "TOKEN_KEY",
    "StreamStateStore",
)

TOKEN_KEY = "stream:token"
LAST_RUN_KEY = "stream:poll:last_run"
#: The cursor only gates "is the next tick due"; a lost key costs one early tick,
#: so it expires rather than accumulating forever in a shared Redis.
LAST_RUN_TTL_SECONDS = 24 * 60 * 60

#: Outcome of the last tick, for the admin health panel. An operator who flips the
#: setting on has no other way to tell "polling works" from "Twitch rejected the
#: credentials" — both look like an empty page, because the tick swallows its own
#: failures on purpose so a Twitch outage cannot kill the scheduler.
POLL_STATUS_KEY = "stream:poll:last_status"
#: Longer than the cursor: a stale "unauthorized 3 days ago" is still the answer to
#: "why is nothing live", whereas an absent key would read as "never ran".
POLL_STATUS_TTL_SECONDS = 7 * 24 * 60 * 60

#: Every tick's outcome, newest first, capped. A Redis list rather than a table:
#: the poller writes no Postgres, and the history only has to answer "when did it
#: start failing" — 200 ticks is over three hours at the default 60s interval.
POLL_HISTORY_KEY = "stream:poll:history"
POLL_HISTORY_LIMIT = 200


class StreamStateStore:
    """Redis-backed live-stream state, bound to one connection."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def live_key(tournament_id: int) -> str:
        return f"stream:live:{int(tournament_id)}"

    @staticmethod
    def snapshot_field(platform: str, channel: str) -> str:
        """Hash field for one channel. Platform-qualified because the same handle
        can exist on two platforms and they are different streams."""
        return f"{platform}:{channel.casefold()}"

    async def read_live(self, tournament_id: int) -> dict[str, dict[str, Any]]:
        """Currently-live channels for a tournament, keyed by :meth:`snapshot_field`.

        Returns an empty mapping when the key is absent or expired — "we do not
        know" and "nobody is live" are the same answer to a reader, and both mean
        the page shows no live badge.
        """
        raw = await self._redis.hgetall(self.live_key(tournament_id))
        if not raw:
            return {}
        snapshots: dict[str, dict[str, Any]] = {}
        for field, value in raw.items():
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                # A malformed field is a bug in the writer, not a reason to blank
                # the whole block for every viewer. Skip it; the next tick
                # overwrites.
                continue
            if isinstance(decoded, dict):
                snapshots[field] = decoded
        return snapshots

    async def write_live(
        self,
        tournament_id: int,
        snapshots: dict[str, dict[str, Any]],
        *,
        ttl_seconds: int,
    ) -> None:
        """Replace the whole live set for a tournament, atomically.

        Full replacement, not a merge: a channel that dropped off the Helix
        response went offline, and merging would leave it "live" forever. The
        DELETE+HSET pair runs in one pipeline so a reader never observes the
        empty window between them. An empty ``snapshots`` deletes the key
        outright.
        """
        key = self.live_key(tournament_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            if snapshots:
                pipe.hset(key, mapping={field: json.dumps(body) for field, body in snapshots.items()})
                pipe.expire(key, ttl_seconds)
            await pipe.execute()

    async def get_last_run(self) -> float | None:
        raw = await self._redis.get(LAST_RUN_KEY)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def set_last_run(self, timestamp: float) -> None:
        await self._redis.set(LAST_RUN_KEY, repr(float(timestamp)), ex=LAST_RUN_TTL_SECONDS)

    async def clear_last_run(self) -> None:
        """Make the next heartbeat due immediately — the admin re-poll's whole job."""
        await self._redis.delete(LAST_RUN_KEY)

    async def read_poll_status(self) -> dict[str, Any] | None:
        """Outcome of the last tick, or ``None`` when none has been recorded yet."""
        raw = await self._redis.get(POLL_STATUS_KEY)
        if raw is None:
            return None
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None

    async def write_poll_status(self, status: dict[str, Any]) -> None:
        """Record the tick's outcome as the latest status and prepend it to the
        capped history, in one transaction so the two never disagree."""
        body = json.dumps(status)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(POLL_STATUS_KEY, body, ex=POLL_STATUS_TTL_SECONDS)
            pipe.lpush(POLL_HISTORY_KEY, body)
            pipe.ltrim(POLL_HISTORY_KEY, 0, POLL_HISTORY_LIMIT - 1)
            pipe.expire(POLL_HISTORY_KEY, POLL_STATUS_TTL_SECONDS)
            await pipe.execute()

    async def read_poll_history(self) -> list[dict[str, Any]]:
        """Recorded tick outcomes, newest first; malformed entries are skipped."""
        history: list[dict[str, Any]] = []
        for raw in await self._redis.lrange(POLL_HISTORY_KEY, 0, POLL_HISTORY_LIMIT - 1):
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict):
                history.append(decoded)
        return history
