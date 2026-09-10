"""Shared helpers for reading latest OW2 rank snapshots and mapping them onto a division grid.

Used by services that need to surface a player's current OW2 rank alongside their
balancer/registration rank (e.g. the rank-delta highlight in the balancing pool). Keeping the
query + role translation + grid normalisation here avoids duplicating it per service.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HERO_TYPE_CLASSES
from shared.core.social import SocialProvider
from shared.division_grid import DivisionGrid
from shared.domain.player_sub_roles import canonical_to_registration_role
from shared.models.identity.social import SocialAccount
from shared.models.ranks.overwatch_rank import UserRankSnapshot


async def fetch_latest_ow_ranks_by_account(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, dict[str, dict[str, int]]]:
    """Latest raw OW2 rank per (user, battle_tag, role), keyed by registration role code.

    Returns ``{user_id: {battle_tag: {registration_role: rank_value}}}`` where ``battle_tag`` is the
    snapshot's denormalized ``Name#1234`` and ``registration_role`` is one of ``tank``/``dps``/
    ``support`` (the snapshot stores the canonical ``HeroClass`` name, e.g. ``damage``, which is
    translated to ``dps`` here). Only ranked snapshots with a non-null ``rank_value`` are considered,
    and only the newest per **(user, battle_tag, role)** by ``captured_at``.

    Keeping one entry per account (rather than collapsing by user) lets callers prefer main accounts
    over declared smurfs and take the maximum rank across accounts. The raw OW SR is returned as-is;
    grid normalisation stays in :func:`normalize_ow_ranks_to_grid`.
    """
    if not user_ids:
        return {}

    # ``rank_snapshot`` is an append-only time series (one row per poll, per
    # role, every ``interval_seconds``), so "newest per account and role" must
    # not read the history: a ``DISTINCT ON`` over ``user_id IN (...)`` fetched
    # and sorted every snapshot the requested users ever had -- millions of rows
    # after a season -- on every registrations-list render. Instead, enumerate
    # the small (account x role) set and probe once per pair; with
    # ``ix_rank_snapshot_latest_ranked`` each probe is a single index descent.
    roles = sa.values(sa.column("role", sa.String), name="roles").data([(role.name,) for role in HERO_TYPE_CLASSES])
    latest = (
        sa.select(UserRankSnapshot.battle_tag, UserRankSnapshot.rank_value)
        .where(
            UserRankSnapshot.social_account_id == SocialAccount.id,
            UserRankSnapshot.role == roles.c.role,
            UserRankSnapshot.rank_value.is_not(None),
            UserRankSnapshot.is_ranked.is_(True),
        )
        .order_by(UserRankSnapshot.captured_at.desc())
        .limit(1)
        .lateral("latest")
    )
    query = (
        sa.select(SocialAccount.user_id, latest.c.battle_tag, roles.c.role, latest.c.rank_value)
        .select_from(SocialAccount)
        .join(roles, sa.true())
        .join(latest, sa.true())
        .where(
            SocialAccount.user_id.in_(user_ids),
            SocialAccount.provider == SocialProvider.BATTLENET,
        )
    )
    result = await session.execute(query)

    out: dict[int, dict[str, dict[str, int]]] = {}
    for user_id, battle_tag, role, rank_value in result:
        registration_role = canonical_to_registration_role(role)
        if registration_role is None:
            continue
        out.setdefault(user_id, {}).setdefault(battle_tag, {})[registration_role] = rank_value
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
