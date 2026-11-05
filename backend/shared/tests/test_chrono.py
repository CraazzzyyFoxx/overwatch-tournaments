"""One tournament chronology (spec 2026-11-05 §11.1): start, then end, then id -- never the id alone."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))

from shared.core.chrono import chrono_sort_key, tournament_chrono_key  # noqa: E402
from shared.models.tournament.tournament import Tournament  # noqa: E402
from shared.testing import create_sqlite_tables, install_postgres_type_shims  # noqa: E402

install_postgres_type_shims()

JAN = datetime(2026, 1, 1, tzinfo=UTC)
JAN_15 = datetime(2026, 1, 15, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)
FEB_2 = datetime(2026, 2, 2, tzinfo=UTC)
FEB_9 = datetime(2026, 2, 9, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)

# (id, start_date, end_date, created_at). 1 has the lowest id and starts last; 2 and 3 start together and 3 ends
# first; 4 is undated and sits at its creation time.
ROWS = (
    (1, MAR, None, JAN),
    (2, FEB, FEB_9, JAN),
    (3, FEB, FEB_2, JAN),
    (4, None, None, JAN_15),
)
CHRONOLOGY = [4, 3, 2, 1]


def _rows() -> list[SimpleNamespace]:
    return [SimpleNamespace(id=i, start_date=s, end_date=e, created_at=c) for i, s, e, c in ROWS]


class ChronoSortKeyTests(TestCase):
    def test_start_then_end_then_id(self) -> None:
        self.assertEqual(CHRONOLOGY, [row.id for row in sorted(_rows(), key=chrono_sort_key)])

    def test_missing_dates_fall_back_like_the_sql(self) -> None:
        self.assertEqual(
            (JAN, JAN, 7), chrono_sort_key(SimpleNamespace(id=7, start_date=None, end_date=None, created_at=JAN))
        )
        self.assertEqual(
            (FEB, FEB, 8), chrono_sort_key(SimpleNamespace(id=8, start_date=FEB, end_date=None, created_at=JAN))
        )


class TournamentChronoKeyTests(TestCase):
    def setUp(self) -> None:
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS tournament")
            create_sqlite_tables(conn, [Tournament.__table__])
            for tid, start, end, created in ROWS:
                conn.execute(
                    sa.insert(Tournament.__table__).values(
                        id=tid,
                        workspace_id=1,
                        name=f"T{tid}",
                        slug=f"t-{tid}",
                        start_date=start,
                        end_date=end,
                        created_at=created,
                    )
                )
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_order_by_the_key(self) -> None:
        ids = self.session.scalars(sa.select(Tournament.id).order_by(*tournament_chrono_key())).all()
        self.assertEqual(CHRONOLOGY, list(ids))

    def test_tuple_comparison_against_the_python_mirror(self) -> None:
        cutoff = SimpleNamespace(id=2, start_date=FEB, end_date=FEB_9, created_at=JAN)
        before = self.session.scalars(
            sa.select(Tournament.id)
            .where(sa.tuple_(*tournament_chrono_key()) < sa.tuple_(*chrono_sort_key(cutoff)))
            .order_by(*tournament_chrono_key())
        ).all()
        self.assertEqual([4, 3], list(before))
