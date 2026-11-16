"""The profile half of an OverFast poll: the account's current profile, its career as a series of changes and its
rename-proof Blizzard id.

Transaction-neutral like ``service``: functions flush, the caller commits. The worker runs this after the poll's ranks
are committed, in a transaction of its own, so nothing here can cost an account its ranks.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.ranks import CareerSnapshotRepository, GameAccountProfileRepository

from .domain import CareerSeries, ParsedProfile, changed_career
from .service import DISCIPLINE

#: How often an account's Blizzard id is (re)resolved through the player search. Re-resolving a known id keeps it
#: right after the account behind a BattleTag changes; the search is one extra request per account per period.
CANONICAL_REFRESH = timedelta(days=7)

profile_repo = GameAccountProfileRepository()
career_repo = CareerSnapshotRepository()


async def canonical_id(session: AsyncSession, social_account_id: int) -> str | None:
    """The account's Blizzard id, if one was ever resolved."""
    profile = await profile_repo.get_by_social_account_id(session, social_account_id)
    return profile.canonical_id if profile else None


async def _latest_series(
    session: AsyncSession, social_account_id: int
) -> dict[tuple[str, str, str], tuple[int | None, str]]:
    """The last stored ``(season, digest)`` of every career series of one account: one ``DISTINCT ON`` over the index."""
    snap = models.CareerSnapshot
    rows = await session.execute(
        sa.select(snap.platform, snap.queue, snap.character, snap.season, snap.digest)
        .where(snap.discipline == DISCIPLINE, snap.social_account_id == social_account_id)
        .ext(distinct_on(snap.platform, snap.queue, snap.character))
        .order_by(snap.platform, snap.queue, snap.character, snap.captured_at.desc(), snap.id.desc())
    )
    return {(platform, queue, character): (season, digest) for platform, queue, character, season, digest in rows}


async def record(
    session: AsyncSession,
    *,
    social_account_id: int,
    profile: ParsedProfile,
    career: Sequence[CareerSeries],
    now: datetime | None = None,
) -> tuple[int, bool]:
    """Rewrite the account's profile and append the career series that changed since their last row.

    Returns the career rows written and whether the account's Blizzard id is due for (re)resolution.
    """
    now = now or datetime.now(UTC)
    row = await profile_repo.get_by_social_account_id(session, social_account_id)
    if row is None:
        row = await profile_repo.create(
            session,
            models.GameAccountProfile(discipline=DISCIPLINE, social_account_id=social_account_id, fetched_at=now),
        )
    row.display_name = profile.display_name
    row.avatar_url = profile.avatar_url
    row.attrs = profile.attrs
    row.upstream_updated_at = profile.upstream_updated_at
    row.fetched_at = now

    changed = changed_career(career, await _latest_series(session, social_account_id))
    if changed:
        await career_repo.create_many(
            session,
            [
                models.CareerSnapshot(
                    discipline=DISCIPLINE,
                    social_account_id=social_account_id,
                    platform=series.platform,
                    queue=series.queue,
                    season=series.season,
                    character=series.character,
                    stats=series.stats,
                    digest=series.digest,
                    captured_at=now,
                )
                for series in changed
            ],
        )
    await session.flush()
    due = row.canonical_checked_at is None or row.canonical_checked_at <= now - CANONICAL_REFRESH
    return len(changed), due


async def set_canonical_id(
    session: AsyncSession, *, social_account_id: int, canonical: str | None, now: datetime | None = None
) -> None:
    """Stamp a resolution attempt; a found id replaces the stored one, a miss keeps it."""
    row = await profile_repo.get_by_social_account_id(session, social_account_id)
    if row is None:
        return
    row.canonical_checked_at = now or datetime.now(UTC)
    if canonical is not None:
        row.canonical_id = canonical
    await session.flush()
