"""Redis-backed session state: RBAC cache, revoked sessions, refresh idempotency.

Ordinary session-cache operations are best-effort: an outage costs database work
or a shorter-lived guarantee. Profile-merge finalization is strict: its session
blacklist and RBAC invalidations must succeed before the database merge commits.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from shared.rbac import RBAC_USER_KEY_PREFIX
from src.core.cache import RedisStore
from src.core.redis import get_redis

# v3: the cached payload now also carries the user's workspace memberships
# (id + slug), so a hit answers the token path with no database round trip at
# all. A v2 entry has no ``workspaces`` key and would look like "member of
# nothing", so the version bump is what retires those entries rather than
# silently stripping a user's workspaces for one TTL.
RBAC_TTL_SECONDS = 60

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

    async def set_rbac(
        self,
        user_id: int,
        *,
        roles: list[str],
        permissions: list[dict[str, str]],
        workspaces: list[list[Any]] | None = None,
        workspace_roles: dict[str, dict] | None = None,
        denies: list[dict[str, Any]] | None = None,
    ) -> None:
        # Every component is stored unconditionally, empty included. A missing
        # key means "unknown, go and load it", so omitting an empty answer
        # ("this user has no denies", "no memberships") would make the entry a
        # permanent partial hit: the load would repeat on every single request
        # and the entry would be rewritten each time.
        payload: dict[str, Any] = {
            "roles": roles,
            "permissions": permissions,
            "workspaces": workspaces or [],
            "workspace_roles": workspace_roles or {},
            "denies": denies or [],
        }
        await self._rbac.put_json(user_id, payload)

    async def invalidate_rbac(self, user_id: int) -> None:
        await self._rbac.drop(user_id)
        logger.info(f"RBAC cache invalidated for user {user_id}")

    # --- Revoked sessions ---

    async def blacklist_session(self, session_id: str, ttl_seconds: int) -> None:
        """Block a revoked session's access tokens until they expire on their own."""
        if not session_id or ttl_seconds <= 0:
            return
        await self._revoked_sessions.mark(session_id, ttl=ttl_seconds)

    async def blacklist_sessions(self, session_ids: set[str], ttl_seconds: int) -> None:
        for session_id in session_ids:
            await self.blacklist_session(session_id, ttl_seconds)

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
            pipeline.delete(*(self._rbac.key(user_id) for user_id in auth_user_ids))
            await pipeline.execute()

    async def is_session_blacklisted(self, session_id: str | None) -> bool:
        """True only when the session is known-revoked (fails open otherwise).

        On an outage we cannot prove the session was revoked; the database
        revocation still applies at the next refresh, so a stale access token
        survives at most one access-token TTL.
        """
        return await self._revoked_sessions.has(session_id or "")

    # --- Refresh idempotency ---

    async def get_refresh_idem(self, token_hash: str) -> dict[str, str] | None:
        return await self._refresh_idem.get_json(token_hash)

    async def set_refresh_idem(self, token_hash: str, access_token: str, refresh_token: str) -> None:
        await self._refresh_idem.put_json(
            token_hash,
            {"access_token": access_token, "refresh_token": refresh_token},
        )


session_cache = SessionCache()
