"""Rank-only re-export: push fresh ranks onto already-materialized players.

The full export (:mod:`src.services.team_export.service`) is destructive — it
deletes the prior ``Team``/``Player`` rows and recreates them, which is exactly
what must NOT happen once a bracket references those teams. When only the numbers
went stale (a rank fixed in the balancer after the export, a draft pick frozen
before the registration had a rank), this updates ``Player.rank`` in place and
touches nothing else.

Rows are matched by ``Player.name`` within the formation node: ``materialize_teams``
wrote that column verbatim from the same payload member, so no identity
re-resolution is needed and a name the export never created simply matches nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.team import Player
from src.services.team_export.materialization import MaterializationTeam

__all__ = ("sync_player_ranks",)

logger = logging.getLogger(__name__)


async def sync_player_ranks(
    session: AsyncSession,
    formation_node_id: int,
    teams: Sequence[MaterializationTeam],
) -> int:
    """Update ``tournament.player.rank`` from an export payload. Flushes; never commits.

    Returns the number of rows whose rank actually changed.
    """
    rank_by_name = {member.name: member.rank for team in teams for member in team.members if member.name}
    if not rank_by_name:
        return 0

    rows = (
        await session.scalars(
            sa.select(Player).where(
                Player.formation_node_id == formation_node_id,
                Player.name.in_(list(rank_by_name)),
            )
        )
    ).all()

    updated = 0
    for player in rows:
        rank = rank_by_name[player.name]
        if player.rank != rank:
            player.rank = rank
            updated += 1

    if updated:
        await session.flush()
    logger.info("Rank re-export updated %s of %s players in formation %s", updated, len(rows), formation_node_id)
    return updated
