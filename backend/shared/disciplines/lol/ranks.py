"""LoL's native rank layer: the newest ranked Solo/Duo snapshot of every Riot account a player owns, the best one.

Read from ``rank.rank_snapshot`` (``discipline='lol'``, ``queue='solo'``); an account whose last successful poll is
older than ``MAX_AGE`` counts for nothing. No Flex fallback: a player without a ranked Solo/Duo snapshot has no native
rank. LoL ranks are per player, not per position, so the value stands for every ``position`` role.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider
from shared.models.identity.social import SocialAccount
from shared.models.ranks.rank import RankAccountState, UserRankSnapshot

__all__ = ("DISCIPLINE", "MAX_AGE", "best_per_user", "latest_rank_rows", "native_ranks", "positions")

DISCIPLINE = "lol"
#: Same freshness rule as Overwatch's ``OW_RANK_MAX_AGE`` (``shared/services/rank_snapshots.py``).
MAX_AGE = timedelta(days=30)


def positions() -> tuple[str, ...]:
    # Imported on call: this module is itself imported lazily by the registry's hooks.
    from shared.disciplines.lol import POSITION

    return tuple(role.code for role in POSITION.roles)


def best_per_user(rows: Iterable[tuple[int, int]]) -> dict[int, dict[str, int]]:
    best: dict[int, int] = {}
    for user_id, value in rows:
        if value > best.get(user_id, -1):
            best[user_id] = value
    return {user_id: dict.fromkeys(positions(), value) for user_id, value in best.items()}


def _latest_solo(user_ids: Any) -> Any:
    """Newest Solo/Duo row of every account of ``user_ids`` (a list or a select), ranked or not: the newest row is
    what says whether the account has a rank now. Scoped to those accounts so the pick walks their series only."""
    snap = UserRankSnapshot
    return (
        sa.select(
            snap.social_account_id,
            snap.handle,
            snap.rank_value,
            snap.division,
            snap.tier,
            snap.is_ranked,
            snap.captured_at,
            snap.id.label("snapshot_id"),
        )
        .where(
            snap.discipline == DISCIPLINE,
            snap.queue == "solo",
            snap.social_account_id.in_(sa.select(SocialAccount.id).where(SocialAccount.user_id.in_(user_ids))),
        )
        .ext(distinct_on(snap.social_account_id))
        .order_by(snap.social_account_id, snap.captured_at.desc(), snap.id.desc())
        .subquery("lol_solo_latest")
    )


def _ranked_fresh_riot(latest: Any) -> list[sa.ColumnElement[bool]]:
    return [
        SocialAccount.provider == SocialProvider.RIOT,
        RankAccountState.discipline == DISCIPLINE,
        RankAccountState.last_success_at >= sa.func.now() - MAX_AGE,
        latest.c.is_ranked.is_(True),
        latest.c.rank_value.is_not(None),
    ]


async def native_ranks(session: AsyncSession, user_ids: Sequence[int]) -> dict[int, dict[str, int]]:
    if not user_ids:
        return {}
    latest = _latest_solo(list(user_ids))
    rows = await session.execute(
        sa.select(SocialAccount.user_id, latest.c.rank_value)
        .select_from(SocialAccount)
        .join(latest, latest.c.social_account_id == SocialAccount.id)
        .join(RankAccountState, RankAccountState.social_account_id == SocialAccount.id)
        .where(*_ranked_fresh_riot(latest))
    )
    return best_per_user((row[0], row[1]) for row in rows.all())


def latest_rank_rows(members: Any, game: str) -> Any:
    """The admin overview's SQL twin of ``native_ranks`` (``DisciplineSpec.native_rank_rows``): one row per account and
    position, ``platform`` = the account's LoL platform (``euw1``)."""
    latest = _latest_solo(sa.select(members.c.player_id))
    roles = sa.values(sa.column("role", sa.String), name=f"rank_native_roles_{game}").data([(r,) for r in positions()])
    return (
        sa.select(
            SocialAccount.user_id.label("user_id"),
            latest.c.handle,
            RankAccountState.region.label("platform"),
            roles.c.role,
            latest.c.rank_value,
            latest.c.division,
            latest.c.tier,
            latest.c.captured_at,
            latest.c.snapshot_id,
        )
        .select_from(SocialAccount)
        .join(latest, latest.c.social_account_id == SocialAccount.id)
        .join(RankAccountState, RankAccountState.social_account_id == SocialAccount.id)
        .join(roles, sa.true())
        .where(*_ranked_fresh_riot(latest))
        .cte(f"rank_native_latest_{game}")
    )
