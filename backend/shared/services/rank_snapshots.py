"""Shared helpers for reading latest OW2 rank snapshots and mapping them onto a division grid.

Used by services that need to surface a player's current OW2 rank alongside their
balancer/registration rank (e.g. the rank-delta highlight in the balancing pool). Keeping the
query + role translation + grid normalisation here avoids duplicating it per service.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.division_grid import DivisionGrid
from shared.domain.player_sub_roles import canonical_to_registration_role
from shared.models.overwatch_rank import UserRankSnapshot


async def fetch_latest_ow_ranks(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, dict[str, int]]:
    """Latest mapped OW2 rank per (user, role), keyed by registration role code.

    Returns ``{user_id: {registration_role: rank_value}}`` where ``registration_role`` is one of
    ``tank``/``dps``/``support`` (snapshot stores the canonical ``RankRole`` value, e.g. ``damage``,
    which is translated to ``dps`` here). Only ranked snapshots with a non-null ``rank_value`` are
    considered, and only the newest per (user, role) by ``captured_at``.
    """
    if not user_ids:
        return {}

    subq = (
        sa.select(
            UserRankSnapshot.user_id,
            UserRankSnapshot.role,
            UserRankSnapshot.rank_value,
            sa.func.row_number()
            .over(
                partition_by=[UserRankSnapshot.user_id, UserRankSnapshot.role],
                order_by=UserRankSnapshot.captured_at.desc(),
            )
            .label("rn"),
        )
        .where(
            UserRankSnapshot.user_id.in_(user_ids),
            UserRankSnapshot.rank_value.is_not(None),
            UserRankSnapshot.is_ranked.is_(True),
        )
        .subquery()
    )
    query = sa.select(subq.c.user_id, subq.c.role, subq.c.rank_value).where(subq.c.rn == 1)
    result = await session.execute(query)

    out: dict[int, dict[str, int]] = {}
    for user_id, role, rank_value in result:
        registration_role = canonical_to_registration_role(role)
        if registration_role is None:
            continue
        out.setdefault(user_id, {})[registration_role] = rank_value
    return out


def normalize_ow_ranks_to_grid(
    raw_by_user: dict[int, dict[str, int]],
    grid: DivisionGrid,
) -> dict[int, dict[str, int]]:
    """Map raw OW2 SR values to workspace-grid rank points (``tier.rank_min``).

    A raw OW2 SR is resolved to a tier via the grid's ``ow_rank_min``/``ow_rank_max`` and replaced
    with that tier's ``rank_min`` so it lives on the same scale as the balancer ``rank_value``.
    Entries whose SR does not fall into any configured tier are dropped, so callers leave the
    corresponding value ``None`` and compute no spurious delta.
    """
    out: dict[int, dict[str, int]] = {}
    for user_id, by_role in raw_by_user.items():
        for role, ow_rank in by_role.items():
            tier = grid.resolve_division_from_ow_rank(ow_rank)
            if tier is not None:
                out.setdefault(user_id, {})[role] = tier.rank_min
    return out
