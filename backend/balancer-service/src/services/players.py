"""The workspace roster with its two rank layers, and the writes that reshape it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.services.member_rank import MemberRankService, member_rank_service
from shared.services.ontology import workspace_discipline
from shared.services.pickup_mix_realtime import emit_pickup_mix_changed
from src.schemas import WorkspacePlayerRead
from src.services import workspace_roster

__all__ = ("WorkspacePlayersService", "workspace_players_service")


def _dump(member: Any, ranks: dict[str, int], author_ranks: dict[str, int]) -> WorkspacePlayerRead:
    return WorkspacePlayerRead(
        member_id=member.member_id,
        player_id=member.player_id,
        identity=member.identity,
        display_name=member.display_name,
        display=member.display,
        # Whether this member has a linked login identity -- a mix's host/
        # co-host picker excludes anyone without one, since both grants are
        # addressed by `auth.user.id` and a member who has never signed in
        # has none.
        auth_user_id=member.auth_user_id,
        # Two layers side by side: the workspace canon everyone sees, and the book
        # being read (the caller's own unless ``author_user_id`` asked otherwise).
        # Collapsing them into one map would hide whether a number is inherited.
        ranks=ranks,
        author_ranks=author_ranks,
    )


def _by_member(layer: dict[tuple[int, str], int]) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for (member_id, role), value in layer.items():
        out.setdefault(member_id, {})[role] = value
    return out


class WorkspacePlayersService:
    def __init__(self, *, ranks: MemberRankService = member_rank_service) -> None:
        self.ranks = ranks

    async def _layers(
        self, session: AsyncSession, workspace_id: int, member_ids: list[int], author_user_id: int, discipline: str
    ) -> tuple[dict[int, dict[str, int]], dict[int, dict[str, int]]]:
        canon = await self.ranks.list_layer(
            session, workspace_id=workspace_id, discipline=discipline, member_ids=member_ids
        )
        author = await self.ranks.list_layer(
            session,
            workspace_id=workspace_id,
            discipline=discipline,
            member_ids=member_ids,
            author_user_id=author_user_id,
        )
        return _by_member(canon), _by_member(author)

    async def page(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str | None,
        search: str | None,
        page: int,
        per_page: int,
        author_user_id: int,
        author_only: bool,
    ) -> tuple[list[WorkspacePlayerRead], int]:
        """One roster page with both rank layers; ``discipline=None`` is the workspace's first enabled one."""
        discipline = await workspace_discipline(session, workspace_id=workspace_id, requested=discipline)
        rows, total = await workspace_roster.roster_page(
            session,
            workspace_id=workspace_id,
            provider=DISCIPLINES[discipline].identity_provider,
            search=search,
            page=page,
            per_page=per_page,
            author_user_id=author_user_id,
            author_only=author_only,
        )
        canon, author = await self._layers(
            session, workspace_id, [row.member_id for row in rows], author_user_id, discipline
        )
        return [_dump(row, canon.get(row.member_id, {}), author.get(row.member_id, {})) for row in rows], total

    async def upsert(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str,
        provider: str,
        handle: str,
        admit_account_holders: bool,
        display_name: str | None,
        actor_user_id: int,
    ) -> tuple[int, str]:
        """Find or enroll the member a game identity denotes; returns (member id, resolved discipline)."""
        discipline = await workspace_discipline(session, workspace_id=workspace_id, requested=discipline)
        member = await workspace_roster.ensure_member_for_identity(
            session,
            workspace_id=workspace_id,
            discipline=discipline,
            provider=provider,
            handle=handle,
            admit_account_holders=admit_account_holders,
            display_name=display_name,
        )
        # Workspace-wide: a renamed or newly enrolled member shows on every
        # mix of the workspace, so no single mix id names the change.
        await emit_pickup_mix_changed(
            session, workspace_id, custom_game_id=None, change="member", actor_user_id=actor_user_id
        )
        return member.id, discipline

    async def get(
        self, session: AsyncSession, *, workspace_id: int, member_id: int, author_user_id: int, discipline: str
    ) -> WorkspacePlayerRead:
        """One member through the roster query, identically shaped to a ``page`` row."""
        roster = await workspace_roster.list_roster(
            session,
            workspace_id=workspace_id,
            provider=DISCIPLINES[discipline].identity_provider,
            member_ids=[member_id],
        )
        row = roster.get(member_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
        canon, author = await self._layers(session, workspace_id, [member_id], author_user_id, discipline)
        return _dump(row, canon.get(member_id, {}), author.get(member_id, {}))

    async def set_ranks(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str,
        workspace_member_id: int,
        ranks: Mapping[str, int],
        clear: Sequence[str],
        author_user_id: int | None,
        actor_user_id: int,
    ) -> dict[str, int]:
        """Write one rank layer of one member; ``author_user_id=None`` is the workspace canon."""
        discipline = await workspace_discipline(session, workspace_id=workspace_id, requested=discipline)
        # ``set_ranks`` runs ``member_in_workspace`` itself, so a member from
        # another workspace 404s before any row is written.
        written = await self.ranks.set_ranks(
            session,
            workspace_id=workspace_id,
            discipline=discipline,
            workspace_member_id=workspace_member_id,
            ranks=ranks,
            clear=clear,
            author_user_id=author_user_id,
        )
        await emit_pickup_mix_changed(
            session, workspace_id, custom_game_id=None, change="rank", actor_user_id=actor_user_id
        )
        return written

    async def authors(self, session: AsyncSession, *, workspace_id: int) -> list[dict[str, Any]]:
        """Every author who has rank-corrected a member here, named, busiest first."""
        counts = await self.ranks.list_authors(session, workspace_id=workspace_id)
        names = await workspace_roster.hosts_by_user_id(
            session, workspace_id=workspace_id, user_ids=[author_user_id for author_user_id, _ in counts]
        )
        return [
            {"user_id": author_user_id, "display_name": names.get(author_user_id), "count": count}
            for author_user_id, count in counts
        ]


workspace_players_service = WorkspacePlayersService()
