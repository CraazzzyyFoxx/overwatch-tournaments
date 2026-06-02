"""Resolve whether registrants' Overwatch profiles are public.

Reads the collected `overwatch_rank.battle_tag_state` (populated by the parser)
and produces a per-registration verdict used by the "All Profiles Open"
admission requirement. Lives in `shared` because both tournament-service
(public reads) and balancer-service (admin reads) need it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums

# A tag whose last fetch landed here counts as a *closed* profile.
_CLOSED_STATUSES = frozenset(
    {
        enums.RankCollectionStatus.private.value,
        enums.RankCollectionStatus.not_found.value,
    }
)


def _registration_tags(registration: Any, scope: str) -> list[str]:
    tags: list[str] = []
    if registration.battle_tag:
        tags.append(registration.battle_tag)
    if scope == "all":
        tags.extend(tag for tag in (registration.smurf_tags_json or []) if tag)
    return tags


async def resolve_profiles_open(
    session: AsyncSession,
    registrations: Sequence[Any],
    *,
    scope: str,
) -> dict[int, bool | None]:
    """Map ``registration.id`` → profile-open verdict.

    - ``True``  — every relevant tag was fetched and is public (status ``ok``).
    - ``False`` — at least one relevant tag is private/not_found (closed wins).
    - ``None``  — unknown: a relevant tag was never fetched / is pending / errored.

    ``scope`` is ``"main"`` (registered battle tag only) or ``"all"`` (incl. smurfs).
    """
    tags_by_reg = {reg.id: _registration_tags(reg, scope) for reg in registrations}
    all_tags = {tag.lower() for tags in tags_by_reg.values() for tag in tags}
    if not all_tags:
        return dict.fromkeys(tags_by_reg, None)

    rows = await session.execute(
        sa.select(models.BattleTagRankState.battle_tag, models.BattleTagRankState.status).where(
            sa.func.lower(models.BattleTagRankState.battle_tag).in_(all_tags)
        )
    )
    status_by_tag: dict[str, str] = {battle_tag.lower(): status for battle_tag, status in rows.all()}

    ok = enums.RankCollectionStatus.ok.value
    verdicts: dict[int, bool | None] = {}
    for reg_id, tags in tags_by_reg.items():
        if not tags:
            verdicts[reg_id] = None
            continue
        statuses = [status_by_tag.get(tag.lower()) for tag in tags]
        if any(status in _CLOSED_STATUSES for status in statuses):
            verdicts[reg_id] = False
        elif all(status == ok for status in statuses):
            verdicts[reg_id] = True
        else:
            verdicts[reg_id] = None
    return verdicts
