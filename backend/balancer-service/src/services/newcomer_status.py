"""Chronologically-correct "has this identity played before" resolution.

Prior participation is judged by tournament chronology, not by whether a
``Player`` row for the identity happens to exist yet, so importing historical
data out of chronological order cannot freeze a wrong answer.

Ordering is the tournament chronology key (``shared.core.chrono``), which is never NULL, so the tuple
comparison needs no sentinel.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.chrono import chrono_sort_key, tournament_chrono_key
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament.team import Player
from shared.models.tournament.tournament import Tournament

__all__ = ("NewcomerScope", "PriorParticipation", "load_prior_participation")

NewcomerScope = Literal["global", "workspace"]


@dataclass(frozen=True)
class PriorParticipation:
    """Identities and discipline-qualified role experience before the target tournament."""

    experienced_user_ids: frozenset[int]
    experienced_user_roles: frozenset[tuple[int, str, str | None]]

    def is_newcomer(self, user_id: int) -> bool:
        return user_id not in self.experienced_user_ids

    def is_newcomer_role(self, user_id: int, role: str | None, *, discipline: str) -> bool:
        return (user_id, discipline, role) not in self.experienced_user_roles


async def load_prior_participation(
    session: AsyncSession,
    *,
    tournament: Tournament,
    user_ids: Collection[int],
) -> PriorParticipation:
    """Batch-resolve prior participation for ``user_ids`` relative to ``tournament``.

    Reads ``tournament.workspace_id``'s ``newcomer_scope`` directly (not via the
    ``tournament.workspace`` relationship, which may not be loaded in an async
    context) to decide whether other workspaces' tournaments count.
    """
    if not user_ids:
        return PriorParticipation(frozenset(), frozenset())

    scope_row = await session.execute(
        sa.select(Workspace.newcomer_scope).where(Workspace.id == tournament.workspace_id)
    )
    scope: NewcomerScope = scope_row.scalar_one_or_none() or "global"

    query = (
        sa.select(WorkspaceMember.player_id, Tournament.discipline, Player.role)
        .select_from(Player)
        .join(WorkspaceMember, WorkspaceMember.id == Player.workspace_member_id)
        .join(Tournament, Tournament.id == Player.tournament_id)
        .where(
            WorkspaceMember.player_id.in_(user_ids),
            sa.tuple_(*tournament_chrono_key()) < sa.tuple_(*chrono_sort_key(tournament)),
        )
    )
    if scope == "workspace":
        query = query.where(Tournament.workspace_id == tournament.workspace_id)

    rows = (await session.execute(query)).all()
    experienced_user_ids = frozenset(user_id for user_id, _, _ in rows)
    experienced_user_roles = frozenset((user_id, discipline, role) for user_id, discipline, role in rows)
    return PriorParticipation(experienced_user_ids, experienced_user_roles)
