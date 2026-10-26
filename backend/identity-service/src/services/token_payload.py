"""Assembly of the RBAC token payload the gateway caches per request.

This is the hottest read path in the service: every authenticated request the
gateway forwards lands here. The Redis RBAC entry is therefore treated as a
complete answer — identity fields, roles, permissions, workspace memberships,
workspace-scoped RBAC and the deny overlay all live in it — so a hit costs zero
database work. A miss (or an outage) loads the whole entry in three statements:
memberships, one role query, denies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository import RoleRepository, UserPermissionDenyRepository, WorkspaceMemberRepository
from src import schemas
from src.core.metrics import RBAC_CACHE_TOTAL
from src.services.players import describe_link
from src.services.session_cache import SessionCache, session_cache

__all__ = ["TokenPayloadBuilder", "UserLoader", "token_payloads", "user_fields"]

#: Loads the account row by id (identity-only); ``None`` when it does not exist.
UserLoader = Callable[[AsyncSession, int], Awaitable["models.AuthUser | None"]]

# Every key ``set_rbac`` writes. An entry missing any of them is a miss: a
# partial entry is never trusted, and never patched up component by component.
_COMPONENTS = ("user", "roles", "permissions", "workspaces", "workspace_roles", "denies")


def user_fields(user: models.AuthUser) -> dict[str, Any]:
    """The account columns the entry carries, so a hit needs no account row."""
    return {
        "email": user.email,
        "username": user.username,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
    }


def _payload(user_id: int, entry: dict[str, Any]) -> schemas.TokenPayload:
    """The wire payload for a complete entry (cached or just loaded: one shape)."""
    workspace_roles: dict[str, dict] = entry["workspace_roles"]  # JSON object keys, hence strings
    no_roles: dict[str, list] = {"roles": [], "permissions": []}
    return schemas.TokenPayload(
        sub=user_id,
        email=entry["user"]["email"],
        username=entry["user"]["username"],
        is_superuser=entry["user"]["is_superuser"],
        roles=entry["roles"],
        permissions=entry["permissions"],
        workspaces=[
            schemas.WorkspaceMembership(
                workspace_id=int(workspace_id),
                slug=slug,
                rbac_roles=workspace_roles.get(str(workspace_id), no_roles)["roles"],
                rbac_permissions=workspace_roles.get(str(workspace_id), no_roles)["permissions"],
            )
            for workspace_id, slug in entry["workspaces"]
        ],
        denies=entry["denies"],
    )


class TokenPayloadBuilder:
    """Assembles the RBAC TokenPayload the gateway caches per request."""

    def __init__(
        self,
        *,
        cache: SessionCache = session_cache,
        roles: RoleRepository = RoleRepository(),
        members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        denies: UserPermissionDenyRepository = UserPermissionDenyRepository(),
    ) -> None:
        self.cache = cache
        self.roles = roles
        self.members = members
        self.denies = denies

    def from_cache(self, user_id: int, entry: dict[str, Any] | None) -> schemas.TokenPayload | None:
        """The payload a complete cache entry answers on its own (zero database work), else None."""
        if not entry or any(component not in entry for component in _COMPONENTS):
            return None
        RBAC_CACHE_TOTAL.labels(result="hit").inc()
        return _payload(user_id, entry)

    async def resolve(
        self,
        session: AsyncSession,
        user_id: int,
        load_user: UserLoader,
        *,
        cached: dict[str, Any] | None = None,
        generation: str | None = None,
    ) -> tuple[schemas.TokenPayload, bool] | None:
        """``(payload, is_active)`` for ``user_id``, loading the account only on a miss.

        ``cached``/``generation`` are the caller's own ``token_state`` read
        (``{}`` for a miss); without them ``rbac_state`` is read here. Either way
        they are read BEFORE ``load_user``: a fill stores the row's account
        fields, and only a generation read before the row fences out a drop
        (deactivation, deletion, profile edit) that commits after it.
        ``None`` when the account does not exist.
        """
        if cached is None:
            cached, generation = await self.cache.rbac_state(user_id)
        payload = self.from_cache(user_id, cached)
        if payload is not None:
            return payload, bool(cached["user"]["is_active"])
        user = await load_user(session, user_id)
        if user is None:
            return None
        return await self.build(session, user, cached=cached or {}, generation=generation), user.is_active

    async def build(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        *,
        cached: dict[str, Any] | None = None,
        generation: str | None = None,
    ) -> schemas.TokenPayload:
        """Build the payload for ``user``, preferring the RBAC cache.

        ``cached``/``generation``: the entry (``{}`` for a miss) and generation
        the caller read BEFORE loading ``user``. Without them the entry is read
        here, after the row, so a miss is answered but never cached: the row's
        account fields could predate a drop that generation would not fence out.
        """
        if cached is None:
            cached, generation = await self.cache.get_rbac(user.id), None
        payload = self.from_cache(user.id, cached)
        if payload is not None:
            # Nothing changed on a hit, so rewriting the entry would only extend
            # its TTL, at the cost of a round trip on every gateway request.
            return payload
        RBAC_CACHE_TOTAL.labels(result="miss").inc()
        return _payload(user.id, await self._fill(session, user, generation))

    async def _fill(self, session: AsyncSession, user: models.AuthUser, generation: str | None) -> dict[str, Any]:
        """Load the whole entry from the database and cache it under ``generation``.

        ``generation`` was read before ``user`` and before these queries, so
        ``set_rbac`` refuses the entry if the user's RBAC or account was dropped
        meanwhile -- these reads may then predate that change. ``None`` (an
        outage, or no read before the row) answers without caching.
        """
        memberships = await self.members.list_memberships_for_auth_user(session, user.id)
        workspace_ids = [workspace_id for workspace_id, _ in memberships]
        (roles, permissions), ws_rbac = await self.roles.rbac_for_user(session, user.id, workspace_ids)
        # Loaded on the DB path too, so the deny overlay still applies when
        # Redis is unavailable — a negative grant must never fail open.
        denies = await self.load_denies(session, user.id)
        entry: dict[str, Any] = {
            "user": user_fields(user),
            "roles": roles,
            "permissions": permissions,
            "workspaces": [[workspace_id, slug] for workspace_id, slug in memberships],
            "workspace_roles": {
                str(workspace_id): {"roles": ws_roles, "permissions": ws_permissions}
                for workspace_id, (ws_roles, ws_permissions) in ws_rbac.items()
            },
            "denies": denies,
        }
        await self.cache.set_rbac(user.id, generation=generation, **entry)
        return entry

    async def load_denies(self, session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
        """Per-user denied ``(resource, action, workspace_id)`` triples.

        ``workspace_id`` is ``None`` for a global deny (blocks everywhere) or a
        concrete workspace id for a deny scoped to that workspace only. See
        ``AuthUser.is_denied`` for how the two are distinguished at check time.
        """
        return await self.denies.list_denied_triples(session, user_id)

    @staticmethod
    def linked_players(user: models.AuthUser) -> list[schemas.AuthLinkedPlayer]:
        """The 0-or-1 player linked to ``user``, as a list for wire-shape compatibility."""
        return [] if user.player is None else [schemas.AuthLinkedPlayer(**describe_link(user.player))]


token_payloads = TokenPayloadBuilder()
