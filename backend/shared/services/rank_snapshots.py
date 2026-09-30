"""Shared helpers for reading latest OW2 rank snapshots and mapping them onto a division grid.

Used by services that need to surface a player's current OW2 rank alongside their
balancer/registration rank (e.g. the rank-delta highlight in the balancing pool). Keeping the
query + role filtering + grid normalisation here avoids duplicating it per service.
"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HERO_TYPE_CLASSES
from shared.core.social import SocialProvider
from shared.division_grid import DivisionGrid
from shared.domain.player_sub_roles import canonical_to_registration_role
from shared.models.identity.social import SocialAccount
from shared.models.ranks.overwatch_rank import BattleTagRankState, UserRankSnapshot

#: How recent an account's last successful poll must be for its rank to count. ``rank_snapshot``
#: keeps changes, so the newest row of an account nobody can poll any more (private profile,
#: renamed tag) still reads as its rank for good -- and, taken as the max across a player's
#: accounts, outranks the account they actually play on.
OW_RANK_MAX_AGE = timedelta(days=30)


async def fetch_latest_ow_ranks_by_account(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, dict[str, dict[str, int]]]:
    """Latest raw OW2 rank per (user, battle_tag, role), keyed by registration role code.

    Returns ``{user_id: {battle_tag: {registration_role: rank_value}}}`` where ``battle_tag`` is the
    snapshot's denormalized ``Name#1234`` and ``registration_role`` is one of ``tank``/``damage``/
    ``support`` (the snapshot stores the canonical ``HeroClass`` name, which is what registration
    uses too; ``flex`` snapshots are dropped). A role counts only when the newest row of its
    **(account, role, platform)** series is ranked: a role that went unranked -- a season reset the
    player has not placed in yet -- has no current rank, however high the last season's was. Across
    platforms the higher one wins. An account whose last successful poll is older than
    :data:`OW_RANK_MAX_AGE` contributes nothing: its newest row is what it was then, not what it is.

    Keeping one entry per account (rather than collapsing by user) lets callers prefer main accounts
    over declared smurfs and take the maximum rank across accounts. The raw OW SR is returned as-is;
    grid normalisation stays in :func:`normalize_ow_ranks_to_grid`.
    """
    if not user_ids:
        return {}

    # Enumerate the small (account x role) set and read each pair's newest row per
    # platform on ``ix_rank_snapshot_series_captured`` rather than a ``DISTINCT ON``
    # over ``user_id IN (...)``, which sorts every requested row on each
    # registrations-list render. ``rank_snapshot`` holds changes, so a pair is a
    # handful of rows. Unranked rows are read on purpose: the newest row being
    # unranked is what says the role has no rank now.
    roles = sa.values(sa.column("role", sa.String), name="roles").data([(role.name,) for role in HERO_TYPE_CLASSES])
    latest = (
        sa.select(UserRankSnapshot.battle_tag, UserRankSnapshot.rank_value, UserRankSnapshot.is_ranked)
        .where(
            UserRankSnapshot.social_account_id == SocialAccount.id,
            UserRankSnapshot.role == roles.c.role,
        )
        .distinct(UserRankSnapshot.platform)
        .order_by(UserRankSnapshot.platform, UserRankSnapshot.captured_at.desc())
        .lateral("latest")
    )
    query = (
        sa.select(SocialAccount.user_id, latest.c.battle_tag, roles.c.role, latest.c.rank_value)
        .select_from(SocialAccount)
        .join(BattleTagRankState, BattleTagRankState.social_account_id == SocialAccount.id)
        .join(roles, sa.true())
        .join(latest, sa.true())
        .where(
            SocialAccount.user_id.in_(user_ids),
            SocialAccount.provider == SocialProvider.BATTLENET,
            BattleTagRankState.last_success_at >= sa.func.now() - OW_RANK_MAX_AGE,
            latest.c.rank_value.is_not(None),
            latest.c.is_ranked.is_(True),
        )
    )
    result = await session.execute(query)

    out: dict[int, dict[str, dict[str, int]]] = {}
    for user_id, battle_tag, role, rank_value in result:
        registration_role = canonical_to_registration_role(role)
        if registration_role is None:
            continue
        by_role = out.setdefault(user_id, {}).setdefault(battle_tag, {})
        by_role[registration_role] = max(by_role.get(registration_role, rank_value), rank_value)
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
