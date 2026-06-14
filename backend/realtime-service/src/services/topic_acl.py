from __future__ import annotations

from collections.abc import Awaitable, Callable

from shared.models.auth_user import AuthUser
from shared.models.tournament import Tournament
from shared.schemas.realtime import TopicPattern
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

AclCheck = Callable[[AuthUser | None, tuple[str, ...], AsyncSession], Awaitable[bool]]


async def _allow_public_bracket(
    user: AuthUser | None,
    groups: tuple[str, ...],
    session: AsyncSession,
) -> bool:
    return True


async def _allow_public_draft(
    user: AuthUser | None,
    groups: tuple[str, ...],
    session: AsyncSession,
) -> bool:
    # Draft spectating is public (anonymous allowed), like the bracket topic.
    # The WebSocket relay is read-only; every draft mutation is an authenticated
    # REST call validated in balancer-service, so no write-auth is enforced here.
    return True


async def _allow_workspace_member(
    user: AuthUser | None,
    groups: tuple[str, ...],
    session: AsyncSession,
) -> bool:
    if user is None or not groups:
        return False
    try:
        workspace_id = int(groups[0])
    except ValueError:
        return False
    return user.is_workspace_member(workspace_id)


async def _allow_tournament_balancer(
    user: AuthUser | None,
    groups: tuple[str, ...],
    session: AsyncSession,
) -> bool:
    # The balancer is an admin tool, so (unlike the public draft/bracket topics)
    # subscribing requires workspace membership. The topic is tournament-scoped,
    # so we resolve the owning workspace before checking membership.
    if user is None or not groups:
        return False
    try:
        tournament_id = int(groups[0])
    except ValueError:
        return False
    workspace_id = await session.scalar(
        select(Tournament.workspace_id).where(Tournament.id == tournament_id)
    )
    if workspace_id is None:
        return False
    return user.is_workspace_member(int(workspace_id))


class TopicAclRegistry:
    def __init__(self) -> None:
        self._rules: list[tuple[TopicPattern, AclCheck]] = []

    def register(self, pattern: str, check: AclCheck) -> None:
        self._rules.append((TopicPattern(pattern), check))

    async def allow(self, user: AuthUser | None, topic: str, session: AsyncSession) -> bool:
        for pattern, check in self._rules:
            groups = pattern.match(topic)
            if groups is None:
                continue
            return await check(user, groups, session)
        return False


topic_acl_registry = TopicAclRegistry()
topic_acl_registry.register("tournament:*:bracket", _allow_public_bracket)
topic_acl_registry.register("tournament:*:draft", _allow_public_draft)
topic_acl_registry.register("tournament:*:balancer", _allow_tournament_balancer)
topic_acl_registry.register("workspace:*:*", _allow_workspace_member)
