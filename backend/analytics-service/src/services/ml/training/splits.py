"""Rolling-origin time-series splits over tournaments.

Tournaments are ordered by ``id`` (proxy for chronological order). For each
cutoff fold the split returns ``(train_ids, val_id, test_id)`` where
``train`` is everything before the validation tournament. Validation always
precedes the test tournament so the model never peeks at the future.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_scope_filter

__all__ = (
    "TimeSeriesSplit",
    "tournament_ids_up_to",
)


@dataclass(frozen=True)
class TimeSeriesSplit:
    """One fold of the rolling-origin split.

    ``train_ids`` is non-empty; ``val_id`` and ``test_id`` may be ``None`` for
    the early folds (when no future tournaments exist).
    """

    train_ids: tuple[int, ...]
    val_id: int | None
    test_id: int | None

    @classmethod
    def from_ids(cls, ids: typing.Sequence[int], *, test_id: int) -> TimeSeriesSplit:
        """Build a single split with the latest non-test id as validation."""
        ordered = sorted(int(i) for i in ids if int(i) < int(test_id))
        if not ordered:
            return cls(train_ids=(), val_id=None, test_id=int(test_id))
        val_id = ordered[-1]
        train_ids = tuple(ordered[:-1])
        return cls(train_ids=train_ids, val_id=val_id, test_id=int(test_id))


async def tournament_ids_up_to(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> list[int]:
    """Return all tournament IDs ``<= cutoff_tournament_id`` in ascending order."""
    query = (
        sa.select(models.Tournament.id)
        .where(
            models.Tournament.id <= cutoff_tournament_id,
            models.Tournament.id >= 1,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Tournament.id)
    )
    result = await session.execute(query)
    return [int(row[0]) for row in result.all()]
