from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS_SERVICE_ROOT = REPO_BACKEND_ROOT / "analytics-service"

for candidate in (str(REPO_BACKEND_ROOT), str(ANALYTICS_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "true"

from shared.schemas.events import BalanceExportedEvent, BalancePlayerSnapshotData  # noqa: E402
from src import models  # noqa: E402
from src.worker.balance_snapshot import write_balance_snapshot  # noqa: E402


class FakeSession:
    """Records deletes/adds so the write path can be asserted without a live DB."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.deletes: list[sa.Delete] = []
        self.flush_count = 0

    async def execute(self, stmt: object) -> None:
        if isinstance(stmt, sa.Delete):
            self.deletes.append(stmt)
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1


def _event() -> BalanceExportedEvent:
    return BalanceExportedEvent(
        tournament_id=42,
        balance_id=123,
        variant_id=None,
        workspace_id=7,
        algorithm="moo",
        division_scope="tournament",
        division_grid_json={"divisions": []},
        team_count=1,
        player_count=2,
        avg_sr_overall=2500.0,
        sr_std_dev=500.0,
        sr_range=1000.0,
        total_discomfort=5,
        off_role_count=1,
        objective_score=None,
        players=[
            BalancePlayerSnapshotData(
                user_id=None,
                team_id=99,
                assigned_role="tank",
                preferred_role="support",
                assigned_rank=3000,
                discomfort=5,
                division_number=None,
                is_captain=True,
                was_off_role=True,
            ),
            BalancePlayerSnapshotData(
                user_id=11,
                team_id=99,
                assigned_role="support",
                preferred_role="support",
                assigned_rank=2000,
                discomfort=0,
                division_number=3,
                is_captain=False,
                was_off_role=False,
            ),
        ],
    )


class BalanceSnapshotConsumerTests(IsolatedAsyncioTestCase):
    async def test_writes_snapshot_and_player_rows(self) -> None:
        session = FakeSession()

        await write_balance_snapshot(session, _event())

        snapshots = [o for o in session.added if isinstance(o, models.AnalyticsBalanceSnapshot)]
        players = [o for o in session.added if isinstance(o, models.AnalyticsBalancePlayerSnapshot)]
        self.assertEqual(1, len(snapshots))
        self.assertEqual(2, len(players))

        snapshot = snapshots[0]
        self.assertEqual(42, snapshot.tournament_id)
        self.assertEqual(123, snapshot.balance_id)
        self.assertEqual(7, snapshot.workspace_id)
        self.assertEqual("moo", snapshot.algorithm)
        self.assertEqual({"divisions": []}, snapshot.division_grid_json)
        self.assertEqual(2, snapshot.player_count)
        self.assertEqual(5, snapshot.total_discomfort)
        self.assertEqual(1, snapshot.off_role_count)

        by_role = {p.assigned_role: p for p in players}
        self.assertTrue(by_role["tank"].is_captain)
        self.assertTrue(by_role["tank"].was_off_role)
        self.assertEqual(3000, by_role["tank"].assigned_rank)
        self.assertEqual(11, by_role["support"].user_id)
        self.assertEqual(3, by_role["support"].division_number)

    async def test_idempotent_upsert_deletes_existing_snapshot_each_time(self) -> None:
        session = FakeSession()

        # Two deliveries of the same balance (duplicate or re-export).
        await write_balance_snapshot(session, _event())
        await write_balance_snapshot(session, _event())

        # A delete-by-key precedes every insert, so re-delivery converges to one row.
        self.assertEqual(2, len(session.deletes))

        snapshots = [o for o in session.added if isinstance(o, models.AnalyticsBalanceSnapshot)]
        players = [o for o in session.added if isinstance(o, models.AnalyticsBalancePlayerSnapshot)]
        self.assertEqual(2, len(snapshots))
        self.assertEqual(4, len(players))

        # The delete targets the analytics.balance_snapshot table.
        for stmt in session.deletes:
            self.assertIs(stmt.table.description, models.AnalyticsBalanceSnapshot.__table__.description)
