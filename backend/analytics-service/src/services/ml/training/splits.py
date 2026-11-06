"""Rolling-origin time-series splits over tournaments.

Tournaments are ordered by ``shared.core.chrono.tournament_chrono_key`` (start, end, id). Numeric id is NOT a
chronology proxy in this database (tournament 62 started months before 61), so id-ordered splits would train on
the future. For each cutoff fold the split returns
``(train_ids, val_id, test_id)`` where ``train`` is everything that started
before the validation tournament.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.chrono import ChronoRow, chrono_sort_key, tournament_chrono_key
from shared.services.workspace_scope import workspace_scope_filter

__all__ = (
    "TimeSeriesSplit",
    "tournaments_up_to",
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
    def from_ids(cls, tournaments: typing.Sequence[ChronoRow], *, test_id: int) -> TimeSeriesSplit:
        """Build a single split with the latest non-test tournament as validation.

        ``tournaments`` MUST come in :func:`tournaments_up_to`'s order and are refused otherwise; their ids are
        opaque labels. Sorting them here would re-impose id-as-time — the future leak this module exists to prevent.
        """
        keys = [chrono_sort_key(t) for t in tournaments]
        if keys != sorted(keys):
            raise ValueError("tournaments are not in chronological order")
        ordered = [int(t.id) for t in tournaments if int(t.id) != int(test_id)]
        if not ordered:
            return cls(train_ids=(), val_id=None, test_id=int(test_id))
        val_id = ordered[-1]
        train_ids = tuple(ordered[:-1])
        return cls(train_ids=train_ids, val_id=val_id, test_id=int(test_id))


async def tournaments_up_to(
    session: AsyncSession,
    cutoff_tournament_id: int,
    *,
    discipline: str,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> list[sa.Row]:
    """Return ``discipline`` tournaments up to and including the cutoff, in tournament chronology.

    Rows carry ``id, start_date, end_date, created_at``. An unknown cutoff id
    yields ``[]`` rather than a silently mis-anchored window. A cutoff that exists but belongs to another discipline,
    or to a workspace outside the requested scope, contradicts the request and raises ``ValueError``: it would anchor
    one game's (or one tenant's) history window on another's date.
    """
    cutoff = (
        await session.execute(
            sa.select(
                *tournament_chrono_key(),
                models.Tournament.discipline,
                models.Tournament.workspace_id,
            ).where(models.Tournament.id == cutoff_tournament_id)
        )
    ).one_or_none()
    if cutoff is None:
        return []
    if cutoff.discipline != discipline:
        raise ValueError(
            f"cutoff tournament {cutoff_tournament_id} belongs to {cutoff.discipline!r}, not {discipline!r}"
        )
    scope = workspace_ids if workspace_ids is not None else (None if workspace_id is None else [workspace_id])
    if scope is not None and cutoff.workspace_id not in {int(w) for w in scope}:
        raise ValueError(f"cutoff tournament {cutoff_tournament_id} is outside the requested workspace scope")
    query = (
        sa.select(
            models.Tournament.id,
            models.Tournament.start_date,
            models.Tournament.end_date,
            models.Tournament.created_at,
        )
        .where(
            sa.tuple_(*tournament_chrono_key()) <= sa.tuple_(*cutoff[:3]),
            models.Tournament.id >= 1,
            models.Tournament.discipline == discipline,
            # Hidden tournaments are containers, not seasons. The per-workspace
            # scrim container holds no ranked roster data, so admitting it here
            # would insert a data-less fold boundary into the rolling-origin split.
            models.Tournament.is_hidden.is_(False),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(*tournament_chrono_key())
    )
    result = await session.execute(query)
    return list(result.all())
