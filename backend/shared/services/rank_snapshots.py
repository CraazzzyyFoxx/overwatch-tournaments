"""Shared helpers for reading latest OW2 rank snapshots.

Used by services that need to surface a player's current OW2 rank alongside their
balancer/registration rank (e.g. the rank-delta highlight in the balancing pool).
"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HERO_TYPE_CLASSES
from shared.core.social import SocialProvider
from shared.domain.player_sub_roles import canonical_to_registration_role
from shared.models.identity.social import SocialAccount
from shared.models.ranks.rank import RankAccountState, UserRankSnapshot

#: How recent an account's last successful poll must be for its rank to count. ``rank_snapshot``
#: keeps changes, so the newest row of an account nobody can poll any more (private profile,
#: renamed tag) still reads as its rank for good -- and, taken as the max across a player's
#: accounts, outranks the account they actually play on.
OW_RANK_MAX_AGE = timedelta(days=30)


async def fetch_latest_ow_ranks_by_account(
    session: AsyncSession,
    user_ids: list[int],
    *,
    discipline: str,
) -> dict[int, dict[str, dict[str, int]]]:
    """Latest raw OW2 rank per (user, handle, role), keyed by registration role code.

    Returns ``{user_id: {handle: {registration_role: rank_value}}}`` where ``handle`` is the
    snapshot's denormalized ``Name#1234`` and ``registration_role`` is one of ``tank``/``damage``/
    ``support`` (the snapshot stores the canonical ``HeroClass`` name, which is what registration
    uses too; ``flex`` snapshots are dropped). A role counts only when the newest row of its
    **(account, role, platform)** series is ranked: a role that went unranked -- a season reset the
    player has not placed in yet -- has no current rank, however high the last season's was. Across
    platforms the higher one wins. An account whose last successful poll is older than
    :data:`OW_RANK_MAX_AGE` contributes nothing: its newest row is what it was then, not what it is.

    Keeping one entry per account (rather than collapsing by user) lets callers prefer main accounts
    over declared smurfs and take the maximum rank across accounts. The raw OW SR is returned as-is;
    grid normalisation stays in :func:`shared.division_grid.normalize_native_ranks_to_grid`.

    ``discipline`` is the caller's game (Overwatch's module passes its own code).
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
        sa.select(UserRankSnapshot.handle, UserRankSnapshot.rank_value, UserRankSnapshot.is_ranked)
        .where(
            UserRankSnapshot.discipline == discipline,
            UserRankSnapshot.social_account_id == SocialAccount.id,
            UserRankSnapshot.role == roles.c.role,
        )
        .ext(distinct_on(UserRankSnapshot.platform))
        .order_by(UserRankSnapshot.platform, UserRankSnapshot.captured_at.desc())
        .lateral("latest")
    )
    query = (
        sa.select(SocialAccount.user_id, latest.c.handle, roles.c.role, latest.c.rank_value)
        .select_from(SocialAccount)
        .join(RankAccountState, RankAccountState.social_account_id == SocialAccount.id)
        .join(roles, sa.true())
        .join(latest, sa.true())
        .where(
            SocialAccount.user_id.in_(user_ids),
            SocialAccount.provider == SocialProvider.BATTLENET,
            RankAccountState.last_success_at >= sa.func.now() - OW_RANK_MAX_AGE,
            latest.c.rank_value.is_not(None),
            latest.c.is_ranked.is_(True),
        )
    )
    result = await session.execute(query)

    out: dict[int, dict[str, dict[str, int]]] = {}
    for user_id, handle, role, rank_value in result:
        registration_role = canonical_to_registration_role(role)
        if registration_role is None:
            continue
        by_role = out.setdefault(user_id, {}).setdefault(handle, {})
        by_role[registration_role] = max(by_role.get(registration_role, rank_value), rank_value)
    return out
