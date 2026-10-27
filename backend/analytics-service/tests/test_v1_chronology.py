"""Per-player analytics histories follow tournament chronology, not tournament id.

Ids are global and not chronological (tournament 62 started months before 61). Chronology is
``(coalesce(start_date, created_at), id)``. The SQL readers run against SQLite (see
``test_hidden_tournament_exclusion`` for the accommodations): the claims under test are properties of the emitted SQL.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

from shared.domain.analytics import PERFORMANCE_MODEL  # noqa: E402
from shared.models.catalog.role import CatalogRole, RoleDimension  # noqa: E402
from shared.models.tournament.player_role import PlayerRole  # noqa: E402
from shared.testing import create_sqlite_tables  # noqa: E402
from tests.ow_analytics import module as ow_module  # noqa: E402

models = importlib.import_module("shared.models")
analytics_flows = importlib.import_module("src.services.analytics.flows")
ratings = importlib.import_module("src.domain.ratings")
drift = importlib.import_module("src.services.ml.training.drift")
shift_features = ow_module("features.shift_features")
player_profile = ow_module("features.player_profile")

JAN, FEB, MAR, MAY = (datetime(2026, month, 1, tzinfo=UTC) for month in (1, 2, 3, 5))


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


def _analytics_rows(ids: tuple[int, int, int]) -> list[dict]:
    """One tank's January, February and March tournaments, under the given ids, in the query's id order."""
    history = ((JAN, 1500, 3, 0), (FEB, 2500, 0, 3), (MAR, 2500, 2, 1))
    rows = [
        {
            "tournament_id": tid,
            "started_at": started,
            "team_id": tid,
            "player_name": "p",
            "player_id": 1000 + tid,
            "user_id": 1,
            "role": "tank",
            "rank": rank,
            "wins": wins,
            "losses": losses,
            "match_count": wins + losses,
            "overall_position": None,
            "team_count": None,
            "performance_points": None,
        }
        for tid, (started, rank, wins, losses) in zip(ids, history, strict=True)
    ]
    return sorted(rows, key=lambda row: row["tournament_id"])


async def _frame(ids: tuple[int, int, int]) -> pd.DataFrame:
    with (
        patch.object(analytics_flows.analytics_service, "get_analytics", AsyncMock(return_value=_analytics_rows(ids))),
        patch.object(analytics_flows.analytics_service, "get_tournament_version_ids", AsyncMock(return_value={})),
        patch.object(analytics_flows, "load_source_grids", AsyncMock(return_value={})),
    ):
        return await analytics_flows.flows_service.get_data_frame(SimpleNamespace(), discipline="overwatch")


async def _scored_by_date(ids: tuple[int, int, int]) -> pd.DataFrame:
    """The scored frame's January, February and March rows, in that order."""
    df = await _frame(ids)
    df = ratings.compute_points_shifts(df)
    df = ratings.compute_linear_metrics(df)
    return df.set_index("tournament_id").loc[list(ids)].reset_index()


class PointsLinearChronologyTests(IsolatedAsyncioTestCase):
    async def test_out_of_order_ids_score_like_chronological_ids(self) -> None:
        chronological = await _scored_by_date((1, 2, 3))
        shuffled = await _scored_by_date((62, 61, 63))

        for column in (
            "previous_cost",
            "previous_div",
            "is_changed",
            "normalized_shift_one",
            "normalized_shift_two",
            "points_shift",
            "points_shift_sd",
            "linear_stable_shift",
            "linear_trend_shift",
            "linear_shift_sd",
            "effective_evidence",
        ):
            with self.subTest(column=column):
                pd.testing.assert_series_equal(chronological[column], shuffled[column])

    async def test_previous_division_chain_follows_start_date(self) -> None:
        january, february, march = (row for _, row in (await _scored_by_date((62, 61, 63))).iterrows())
        self.assertNotEqual(january["div"], february["div"])  # precondition: 1500 and 2500 are different divisions

        self.assertEqual(62, january["tournament_id"])
        self.assertTrue(pd.isna(january["previous_cost"]))
        self.assertEqual(1500, february["previous_cost"])
        self.assertEqual(january["div"], february["previous_div"])
        self.assertTrue(february["is_changed"])
        self.assertEqual(2500, march["previous_cost"])
        self.assertFalse(march["is_changed"])


class AtomicRecalculationTests(IsolatedAsyncioTestCase):
    async def test_every_write_commits_at_once_after_the_read_transaction_ends(self) -> None:
        calls: list[str] = []
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=lambda *args, **kwargs: calls.append("execute")),
            add=lambda obj: calls.append("add"),
            commit=AsyncMock(side_effect=lambda: calls.append("commit")),
        )
        frame = await _frame((1, 2, 3))
        algorithm = SimpleNamespace(id=1)
        no_replay = AsyncMock(return_value=({}, False))
        nothing_later = AsyncMock(return_value=[])

        with (
            patch.object(analytics_flows, "tournament_discipline", AsyncMock(return_value="overwatch")),
            patch.object(analytics_flows.flows_service, "get_data_frame", AsyncMock(return_value=frame)),
            patch.object(analytics_flows.analytics_service, "get_players_by_tournament_id", AsyncMock(return_value=[])),
            patch.object(analytics_flows.analytics_service, "ensure_algorithm", AsyncMock(return_value=algorithm)),
            patch.object(analytics_flows.analytics_service, "computed_tournament_ids_after", nothing_later),
            patch.object(analytics_flows.flows_service, "compute_openskill_shift_map", no_replay),
        ):
            algorithms = await analytics_flows.flows_service.recalculate_analytics(session, 3, workspace_id=1)

        self.assertEqual([analytics_flows.POINTS, analytics_flows.LINEAR, analytics_flows.OPENSKILL], algorithms)
        self.assertIn("execute", calls)
        self.assertIn("add", calls)
        # The read transaction ends before the CPU pass and any write; every write then commits at once, last.
        self.assertEqual([0, len(calls) - 1], [i for i, c in enumerate(calls) if c == "commit"])


class DriftChronologyTests(TestCase):
    def test_recent_window_is_the_chronologically_latest_tournaments(self) -> None:
        # Ids 4..1 in start order: the two latest-started tournaments (2, 1) carry a wide spread the
        # earlier two (4, 3) lack.
        narrow, wide = np.linspace(-0.1, 0.1, 10), np.linspace(-3.0, 3.0, 10)
        df = pd.DataFrame(
            {
                "tournament_id": np.repeat([4, 3, 2, 1], 10),
                "x": np.concatenate([narrow, narrow, wide, wide]),
            }
        )

        by_start = drift.compute_drift_report(df, [4, 3, 2, 1], threshold=5.0, recent_window=2)
        by_id = drift.compute_drift_report(df, [1, 2, 3, 4], threshold=5.0, recent_window=2)

        self.assertEqual(["x"], by_start["flags"])
        self.assertEqual([], by_id["flags"])


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` (no async SQLite driver is installed)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement):  # noqa: ANN001, ANN202
        return self._session.execute(statement)

    async def scalars(self, statement):  # noqa: ANN001, ANN202
        return self._session.scalars(statement)


class _Database:
    TABLES = (
        models.Tournament.__table__,
        models.Player.__table__,
        PlayerRole.__table__,
        CatalogRole.__table__,
        RoleDimension.__table__,
        models.WorkspaceMember.__table__,
        models.AnalyticsAlgorithm.__table__,
        models.AnalyticsPerformance.__table__,
        # Read (empty) by the profile's match-log stats query.
        models.Encounter.__table__,
        models.EncounterTeam.__table__,
        models.StatsMatch.__table__,
        models.StatsMatchTeam.__table__,
        models.StatsFact.__table__,
        models.StatDef.__table__,
    )

    def __init__(self) -> None:
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in self.TABLES if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            create_sqlite_tables(conn, self.TABLES)
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)
        self._next_id = 1
        self._members: dict[int, int] = {}
        self.insert(
            RoleDimension.__table__,
            id=1,
            discipline="overwatch",
            code="player_role",
            name="Role",
            selection_mode="single",
            rated=True,
        )
        self.insert(CatalogRole.__table__, id=1, dimension_id=1, code="tank", name="Tank", attrs={})
        self.insert(models.AnalyticsAlgorithm.__table__, id=1, name=PERFORMANCE_MODEL.algorithm_name)

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    def insert(self, table, **values) -> None:  # noqa: ANN001, ANN003
        self.session.execute(sa.insert(table).values(**values))

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def tournament(self, tournament_id: int, started: datetime) -> None:
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=1,
            name=f"Tournament {tournament_id}",
            slug=f"tournament-{tournament_id}",
            is_hidden=False,
            start_date=started,
        )

    def player(self, tournament_id: int, *, user_id: int, rank: int) -> int:
        if user_id not in self._members:
            self._members[user_id] = self._id()
            self.insert(models.WorkspaceMember.__table__, id=self._members[user_id], workspace_id=1, player_id=user_id)
        player_id = self._id()
        self.insert(
            models.Player.__table__,
            id=player_id,
            tournament_id=tournament_id,
            team_id=tournament_id,
            workspace_member_id=self._members[user_id],
            name="p",
            rank=rank,
            is_substitution=False,
            is_newcomer=False,
            is_newcomer_role=False,
        )
        self.insert(PlayerRole.__table__, player_id=player_id, dimension_id=1, role_id=1)
        return player_id

    def performance(self, tournament_id: int, player_id: int, raw_value: float) -> None:
        self.insert(
            models.AnalyticsPerformance.__table__,
            id=self._id(),
            tournament_id=tournament_id,
            player_id=player_id,
            algorithm_id=1,
            impact_score=50.0,
            raw_value=raw_value,
        )


class _DatabaseTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = _Database()

    def tearDown(self) -> None:
        self.db.close()


class RankHistoryChronologyTests(_DatabaseTestCase):
    async def _history(self, tournament_ids: list[int], **kwargs) -> pd.DataFrame:  # noqa: ANN003
        with patch.object(shift_features, "load_division_grids", AsyncMock(return_value={})):
            return await shift_features.load_player_rank_history(self.db.shim, tournament_ids, **kwargs)

    async def test_prior_and_next_division_follow_start_date(self) -> None:
        for tid, started, rank in ((61, FEB, 2500), (62, JAN, 1500), (63, MAR, 3500)):
            self.db.tournament(tid, started)
            self.db.player(tid, user_id=10, rank=rank)

        history = await self._history([61], history_through_tournament_id=63)

        self.assertEqual([62, 61, 63], history["tournament_id"].tolist())
        rows = {int(row.tournament_id): row for row in history.itertuples()}
        self.assertEqual(3, len({rows[tid].div for tid in rows}))  # precondition: three distinct divisions
        self.assertEqual(rows[62].div, rows[61].prior_div)
        self.assertEqual(rows[63].div, rows[61].next_tournament_div)
        self.assertEqual(2, rows[61].tournaments_played)

    async def test_history_runs_through_the_latest_started_requested_tournament(self) -> None:
        for tid, started in ((61, FEB), (62, JAN), (63, MAR)):
            self.db.tournament(tid, started)
            self.db.player(tid, user_id=10, rank=2500)

        history = await self._history([61])

        # 62 started before 61 (in the history); 63 started after it (beyond the horizon).
        self.assertEqual([62, 61], history["tournament_id"].tolist())


class PlayerProfileWindowTests(_DatabaseTestCase):
    async def test_history_window_is_the_most_recent_tournaments_by_start_date(self) -> None:
        for tid, started, raw_value in ((60, MAY, 0.6), (61, FEB, 0.1), (62, JAN, 0.2), (63, MAR, 0.3)):
            self.db.tournament(tid, started)
            self.db.performance(tid, self.db.player(tid, user_id=10, rank=2500), raw_value)

        with patch.object(player_profile, "compute_mvp_dominance", AsyncMock(return_value=pd.DataFrame())):
            profile = await player_profile.load_player_signal_profile(self.db.shim, 61, history_depth=1, workspace_id=1)

        # Tournament 61 plus the one tournament started before it (62), oldest first; 60 started after 61.
        self.assertEqual([0.2, 0.1], profile.iloc[0]["raw_value_history"])
