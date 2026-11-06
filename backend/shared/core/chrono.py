"""The one tournament chronology: start, then end, then id.

Ids follow creation, not play, so the id alone never orders tournaments in time. The key is never NULL
(`created_at` is NOT NULL), so callers never add `NULLS LAST`. Descending is
`*(c.desc() for c in tournament_chrono_key())`.
"""

from datetime import datetime
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import InstrumentedAttribute

from shared.models.tournament.tournament import Tournament

__all__ = ("ChronoKey", "ChronoRow", "chrono_sort_key", "tournament_chrono_key")

type ChronoKey = tuple[datetime, datetime, int]


class ChronoRow(Protocol):
    """Read-only so a frozen `sa.Row` and a `SimpleNamespace` both satisfy it."""

    @property
    def id(self) -> int: ...
    @property
    def start_date(self) -> datetime | None: ...
    @property
    def end_date(self) -> datetime | None: ...
    @property
    def created_at(self) -> datetime: ...


def tournament_chrono_key() -> tuple[
    sa.ColumnElement[datetime], sa.ColumnElement[datetime], InstrumentedAttribute[int]
]:
    return (
        sa.func.coalesce(Tournament.start_date, Tournament.created_at),
        sa.func.coalesce(Tournament.end_date, Tournament.start_date, Tournament.created_at),
        Tournament.id,
    )


def chrono_sort_key(row: ChronoRow) -> ChronoKey:
    """Python mirror of `tournament_chrono_key()`."""
    start = row.start_date or row.created_at
    return (start, row.end_date or start, row.id)
