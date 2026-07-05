"""Batched resolvers that DERIVE the legacy Challonge identifiers from the
normalized mapping tables.

During the Challonge consolidation the deprecated ``challonge_id`` /
``challonge_slug`` columns on ``tournament`` / ``stage`` / ``group`` and
``encounter.challonge_id`` are being retired (see migration
``dbarch04b_challonge_drop_legacy``). Services must stop reading those columns,
yet the public API still EXPOSES ``challonge_id`` / ``challonge_slug`` on
Tournament / Stage / Encounter (the frontend builds challonge.com links from the
slugs and uses ``encounter.challonge_id`` as a bracket key). These resolvers
reconstruct the exact same values from the normalized tables instead:

* ``tournament.challonge_id`` / ``challonge_slug``
    → ``challonge_source`` WHERE ``tournament_id = T`` AND ``source_type = 'tournament'``
      (``challonge_tournament_id`` / ``slug``).
* ``stage.challonge_id`` / ``challonge_slug``
    → ``challonge_source`` WHERE ``stage_id = S`` AND
      ``source_type IN ('tournament', 'stage')``.
* ``encounter.challonge_id``
    → ``challonge_match_mapping.challonge_match_id`` WHERE ``encounter_id = E``.

Every resolver is BATCHED (one query for a whole page of ids) so callers avoid
N+1, and is service-agnostic so both tournament-service and parser-service can
reuse it. Values are deduplicated deterministically by the mapping row's own id
(lowest id wins) to match the legacy single-value column semantics.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.challonge import ChallongeMatchMapping, ChallongeSource

__all__ = (
    "ChallongeRef",
    "resolve_tournament_challonge",
    "resolve_stage_challonge",
    "resolve_encounter_challonge",
)

# (challonge_id, slug) — mirrors the legacy pair of columns.
ChallongeRef = tuple[int | None, str | None]


def _unique_ints(values: Iterable[int | None]) -> list[int]:
    seen: dict[int, None] = {}
    for value in values:
        if value is not None:
            seen.setdefault(value, None)
    return list(seen)


async def resolve_tournament_challonge(
    session: AsyncSession, tournament_ids: Iterable[int | None]
) -> dict[int, ChallongeRef]:
    """Map ``tournament_id -> (challonge_id, slug)`` from the tournament-scoped source."""
    ids = _unique_ints(tournament_ids)
    if not ids:
        return {}
    rows = await session.execute(
        sa.select(
            ChallongeSource.tournament_id,
            ChallongeSource.challonge_tournament_id,
            ChallongeSource.slug,
        )
        .where(
            ChallongeSource.tournament_id.in_(ids),
            ChallongeSource.source_type == "tournament",
        )
        .order_by(ChallongeSource.id.asc())
    )
    result: dict[int, ChallongeRef] = {}
    for tournament_id, challonge_id, slug in rows.all():
        result.setdefault(tournament_id, (challonge_id, slug))
    return result


async def resolve_stage_challonge(
    session: AsyncSession, stage_ids: Iterable[int | None]
) -> dict[int, ChallongeRef]:
    """Map ``stage_id -> (challonge_id, slug)`` from the stage-scoped source.

    Filters ``source_type IN ('tournament','stage')`` to reproduce the legacy
    ``stage.challonge_id`` (the shared bracket is stored either as a dedicated
    ``'stage'`` source or as the ``'tournament'`` source enriched with a
    ``stage_id``). A ``'group'``/``'playoff'`` source that happens to share the
    stage_id must NOT be returned as the stage's value.
    """
    ids = _unique_ints(stage_ids)
    if not ids:
        return {}
    rows = await session.execute(
        sa.select(
            ChallongeSource.stage_id,
            ChallongeSource.challonge_tournament_id,
            ChallongeSource.slug,
        )
        .where(
            ChallongeSource.stage_id.in_(ids),
            ChallongeSource.source_type.in_(("tournament", "stage")),
        )
        .order_by(ChallongeSource.id.asc())
    )
    result: dict[int, ChallongeRef] = {}
    for stage_id, challonge_id, slug in rows.all():
        if stage_id is not None:
            result.setdefault(stage_id, (challonge_id, slug))
    return result


async def resolve_encounter_challonge(
    session: AsyncSession, encounter_ids: Iterable[int | None]
) -> dict[int, int]:
    """Map ``encounter_id -> challonge_match_id`` from ``challonge_match_mapping``."""
    ids = _unique_ints(encounter_ids)
    if not ids:
        return {}
    rows = await session.execute(
        sa.select(
            ChallongeMatchMapping.encounter_id,
            ChallongeMatchMapping.challonge_match_id,
        )
        .where(ChallongeMatchMapping.encounter_id.in_(ids))
        .order_by(ChallongeMatchMapping.id.asc())
    )
    result: dict[int, int] = {}
    for encounter_id, challonge_match_id in rows.all():
        result.setdefault(encounter_id, challonge_match_id)
    return result
