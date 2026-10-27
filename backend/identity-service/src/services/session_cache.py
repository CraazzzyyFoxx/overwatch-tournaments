"""Redis-backed session state: RBAC cache, revoked sessions, refresh idempotency.

Ordinary session-cache operations are best-effort: an outage costs database work
or a shorter-lived guarantee. Profile-merge finalization is strict: its session
blacklist and RBAC invalidations must succeed before the database merge commits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from redis.exceptions import RedisError

from shared.rbac import RBAC_USER_KEY_PREFIX
from shared.schemas.realtime import WorkspaceEventEnvelope
from shared.services.realtime.scope import Scope
from shared.services.realtime_publisher import publish_envelope_to_redis
from src.core.cache import _UNAVAILABLE, RedisStore
from src.core.redis import get_redis

# The cached payload carries the user's workspace memberships (id + slug) and
# identity fields too, so a hit answers the token path with no database round
# trip at all. 600 s is safe only because every RBAC/identity mutation drops the
# entry explicitly (and identity flushes them all at startup, for drops that
# expired in the queue while it was down); the TTL is the backstop, not the bound.
RBAC_TTL_SECONDS = 600

# Bumped by every RBAC drop. A fill reads it BEFORE it loads anything -- the
# account row included -- in the same MGET as the entry, and writes only while
# it is unchanged (``_SET_IF_GENERATION``), so a validation that read the
# database before a membership or account commit cannot put the pre-change
# entry back after that change's invalidation. The TTL only has to outlive one
# fill: a generation that expired mid-fill reads "0" again, the value a fill
# that started before the very first bump would still match.
RBAC_GENERATION_KEY_PREFIX = "rbac:gen:"
RBAC_GENERATION_TTL_SECONDS = 3600

# KEYS: entry, generation. ARGV: generation the fill read, payload, TTL.
_SET_IF_GENERATION = """
if (redis.call('GET', KEYS[2]) or '0') ~= ARGV[1] then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""

# ``user:{id}:rbac`` -- announced after every RBAC drop so the gateway evicts
# the principals and workspace memberships it cached for that user
# (gateway/internal/principal and ws.TopicRevoker, which mirror this topic).
# Ephemeral (event_id 0): nothing to replay.
RBAC_DOMAIN = "rbac"
RBAC_CHANGED_EVENT = "rbac.changed"

# Concurrent refreshes of the same token must not look like a reuse attack: the
# first rotation publishes its result here for the others to read.
REFRESH_IDEM_TTL_SECONDS = 30


class SessionCache:
    """Owns the three Redis namespaces that back a live session."""

    def __init__(
        self,
        *,
        rbac_ttl: int = RBAC_TTL_SECONDS,
        refresh_idem_ttl: int = REFRESH_IDEM_TTL_SECONDS,
    ) -> None:
        self._rbac = RedisStore(RBAC_USER_KEY_PREFIX, ttl=rbac_ttl, purpose="RBAC cache")
        self._rbac_generation = RedisStore(
            RBAC_GENERATION_KEY_PREFIX, ttl=RBAC_GENERATION_TTL_SECONDS, purpose="RBAC generation"
        )
        # Access tokens are stateless and short-lived, so revoking a session
        # (logout / revoke / reuse-detection) must also block the still-valid
        # access tokens carrying its ``sid``. Entries are written with a TTL
        # equal to the access-token lifetime, so the key self-expires once no
        # live token can reference it — hence no default TTL here.
        self._revoked_sessions = RedisStore("auth:sid:revoked:", ttl=0, purpose="session blacklist")
        self._refresh_idem = RedisStore("refresh:idem:", ttl=refresh_idem_ttl, purpose="refresh idempotency")

    # --- RBAC ---

    async def get_rbac(self, user_id: int) -> dict[str, Any] | None:
        """Cached RBAC payload, or None on a miss/outage."""
        return await self._rbac.get_json(user_id)

    async def rbac_state(self, user_id: int) -> tuple[dict[str, Any] | None, str | None]:
        """``(RBAC entry, generation)`` in ONE round trip; read it BEFORE loading the user.

        The generation is what a fill hands to ``set_rbac``. ``(None, None)`` on
        an outage -- nothing could be written then anyway.
        """
        entry, generation, _revoked = await self.token_state(user_id, None)
        return entry, generation

    async def token_state(self, user_id: int, session_id: str | None) -> tuple[dict[str, Any] | None, str | None, bool]:
        """``(RBAC entry, generation, sid revoked?)`` in ONE round trip -- the token path's whole Redis cost.

        Fails soft to ``(None, None, False)``: a miss (the database answers, and
        nothing is cached) and not-revoked. On an outage revocation cannot be
        proven; the database revocation still applies at the next refresh, so a
        stale access token survives at most one access-token TTL.
        """
        keys = [self._rbac.key(user_id), self._rbac_generation.key(user_id)]
        if session_id:
            keys.append(self._revoked_sessions.key(session_id))
        try:
            raw, generation, *revoked = await get_redis().mget(keys)
        except _UNAVAILABLE as exc:
            self._rbac._degraded("read", exc)
            return None, None, False
        entry = await self._rbac.decode(user_id, raw)
        return entry, generation or "0", any(flag is not None for flag in revoked)

    async def set_rbac(
        self,
        user_id: int,
        *,
        generation: str | None,
        user: dict[str, Any],
        roles: list[str],
        permissions: list[dict[str, str]],
        workspaces: list[list[Any]] | None = None,
        workspace_roles: dict[str, dict] | None = None,
        denies: list[dict[str, Any]] | None = None,
    ) -> None:
        """Store what a fill loaded, unless the user's RBAC was dropped since it read ``generation``.

        ``user`` is ``{email, username, is_active, is_superuser}``: with it a hit
        answers ``validate_token`` without loading the account row.
        """
        if generation is None:
            return
        # Every component is stored unconditionally, empty included. A missing
        # key means "unknown, go and load it", so omitting an empty answer
        # ("this user has no denies", "no memberships") would make the entry a
        # permanent partial hit: the load would repeat on every single request
        # and the entry would be rewritten each time.
        payload: dict[str, Any] = {
            "user": user,
            "roles": roles,
            "permissions": permissions,
            "workspaces": workspaces or [],
            "workspace_roles": workspace_roles or {},
            "denies": denies or [],
        }
        try:
            await get_redis().eval(
                _SET_IF_GENERATION,
                2,
                self._rbac.key(user_id),
                self._rbac_generation.key(user_id),
                generation,
                json.dumps(payload),
                self._rbac.ttl,
            )
        except _UNAVAILABLE as exc:
            self._rbac._degraded("write", exc)

    async def invalidate_rbac(self, *user_ids: int) -> None:
        if not user_ids:
            return
        try:
            async with get_redis().pipeline(transaction=True) as pipeline:
                self._queue_rbac_drop(pipeline, user_ids)
                await pipeline.execute()
        except _UNAVAILABLE as exc:
            self._rbac._degraded("invalidation", exc)
        else:
            for user_id in user_ids:
                logger.info(f"RBAC cache invalidated for user {user_id}")
        await self._announce_rbac_changed(user_ids)

    def _queue_rbac_drop(self, pipeline: Any, user_ids: tuple[int, ...] | list[int]) -> None:
        """Drop the entries and bump their generations, so no fill already in flight can restore them."""
        for user_id in user_ids:
            generation_key = self._rbac_generation.key(user_id)
            pipeline.incr(generation_key)
            pipeline.expire(generation_key, self._rbac_generation.ttl)
            pipeline.delete(self._rbac.key(user_id))

    async def _announce_rbac_changed(self, user_ids: tuple[int, ...] | list[int]) -> None:
        """Tell the gateway, AFTER the Redis entries are gone, to forget these users' principals.

        Best-effort like the cache itself: a lost frame leaves the gateway's
        own short token TTL as the bound.
        """
        for user_id in user_ids:
            envelope = WorkspaceEventEnvelope(
                event_id=0, event_type=RBAC_CHANGED_EVENT, occurred_at=datetime.now(UTC), data={}
            )
            try:
                await publish_envelope_to_redis(
                    get_redis(), topic=Scope.user(user_id).domain_topic(RBAC_DOMAIN), envelope=envelope
                )
            except (RedisError, OSError, RuntimeError) as exc:
                logger.warning(f"RBAC change for user {user_id} not announced to the gateway: {exc}")

    async def flush_rbac_cache(self) -> int:
        """Drop every cached RBAC entry; returns how many (0 on an outage).

        Run at identity startup: a ``WorkspaceMemberChangedEvent`` that expired
        unread in its queue (2-minute TTL) while identity was down would
        otherwise leave its stale entry alive for up to ``RBAC_TTL_SECONDS``.
        """
        flushed = 0
        try:
            client = get_redis()
            batch: list[str] = []
            async for key in client.scan_iter(match=f"{RBAC_USER_KEY_PREFIX}*", count=500):
                batch.append(key)
                if len(batch) == 500:
                    flushed += await client.unlink(*batch)
                    batch.clear()
            if batch:
                flushed += await client.unlink(*batch)
        except _UNAVAILABLE as exc:
            self._rbac._degraded("invalidation", exc)
        else:
            logger.info(f"RBAC cache flushed: {flushed} entries")
        return flushed

    # --- Revoked sessions ---

    async def blacklist_session(self, session_id: str, ttl_seconds: int) -> None:
        """Block a revoked session's access tokens until they expire on their own."""
        if not session_id or ttl_seconds <= 0:
            return
        await self._revoked_sessions.mark(session_id, ttl=ttl_seconds)

    async def blacklist_sessions(self, session_ids: set[str], ttl_seconds: int) -> None:
        """``blacklist_session`` for many sids, in one pipelined round trip."""
        session_ids = {session_id for session_id in session_ids if session_id}
        if not session_ids or ttl_seconds <= 0:
            return
        try:
            async with get_redis().pipeline(transaction=False) as pipeline:
                for session_id in sorted(session_ids):
                    pipeline.set(self._revoked_sessions.key(session_id), "1", ex=ttl_seconds)
                await pipeline.execute()
        except _UNAVAILABLE as exc:
            self._revoked_sessions._degraded("write", exc)

    async def finalize_profile_merge(
        self,
        auth_user_ids: list[int],
        session_ids: set[str],
        ttl_seconds: int,
    ) -> None:
        """Retire affected claims atomically; an unavailable Redis must abort the merge."""
        if ttl_seconds <= 0:
            raise ValueError("Profile merge requires a positive access-token lifetime.")
        async with get_redis().pipeline(transaction=True) as pipeline:
            for session_id in sorted(session_ids):
                pipeline.set(self._revoked_sessions.key(session_id), "1", ex=ttl_seconds)
            self._queue_rbac_drop(pipeline, auth_user_ids)
            await pipeline.execute()
        await self._announce_rbac_changed(auth_user_ids)

    # --- Refresh idempotency ---

    async def get_refresh_idem(self, token_hash: str) -> dict[str, str] | None:
        return await self._refresh_idem.get_json(token_hash)

    async def set_refresh_idem(self, token_hash: str, access_token: str, refresh_token: str) -> None:
        await self._refresh_idem.put_json(
            token_hash,
            {"access_token": access_token, "refresh_token": refresh_token},
        )


session_cache = SessionCache()
