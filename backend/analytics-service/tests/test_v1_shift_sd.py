"""v1 shifts carry a posterior sd; Linear restarts at a division move and weighs a tournament by its maps.

Points, Linear and OpenSkill each persist ``(shift, shift_sd)`` in canonical divisions; recalculating a tournament also
rewrites the later tournaments of the workspace that already have v1 rows. The unit frames go through the real
``get_data_frame`` (the analytics query is faked), so ``is_changed`` and the placement score are the production ones;
the last test runs the whole recalculation on the migrated Postgres schema (skipped without a test database).
"""

from __future__ import annotations

import asyncio
import importlib
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, call, patch

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

from shared.division_grid import DEFAULT_GRID, DivisionGrid, DivisionTier  # noqa: E402
from shared.testing import create_sqlite_tables  # noqa: E402

models = importlib.import_module("shared.models")
analytics_flows = importlib.import_module("src.services.analytics.flows")
analytics_service = importlib.import_module("src.services.analytics.service").analytics_service
ratings = importlib.import_module("src.domain.ratings")

JAN, FEB, MAR, APR, MAY, JUN = (datetime(2026, month, 1, tzinfo=UTC) for month in range(1, 7))


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


def _row(
    tid: int,
    started: datetime,
    *,
    user: int = 1,
    rank: int | None,
    wins: int,
    losses: int,
    position: int | None = None,
    teams: int | None = None,
    newcomer: bool = False,
    match_count: int | None = None,
) -> dict:
    """One analytics-query row: ``user``'s tank in tournament ``tid``."""
    return {
        "tournament_id": tid,
        "started_at": started,
        "team_id": tid * 10 + user,
        "player_name": f"p{user}",
        "player_id": tid * 100 + user,
        "user_id": user,
        "role": "tank",
        "rank": rank,
        "wins": wins,
        "losses": losses,
        "match_count": wins + losses if match_count is None else match_count,
        "overall_position": position,
        "team_count": teams,
        "performance_points": None,
        "is_newcomer": newcomer,
        "is_newcomer_role": newcomer,
    }


async def _frame(rows: list[dict]) -> pd.DataFrame:
    with (
        patch.object(analytics_flows.analytics_service, "get_analytics", AsyncMock(return_value=rows)),
        patch.object(analytics_flows.analytics_service, "get_tournament_version_ids", AsyncMock(return_value={})),
        patch.object(analytics_flows, "load_source_grids", AsyncMock(return_value={})),
    ):
        return await analytics_flows.flows_service.get_data_frame(SimpleNamespace(), discipline="overwatch")


async def _scored(rows: list[dict]) -> pd.DataFrame:
    """The scored frame, indexed by ``player_id`` (``tid * 100 + user``)."""
    df = ratings.compute_points_shifts(await _frame(rows))
    return ratings.compute_linear_metrics(df).set_index("player_id")


class LinearHistoryTests(IsolatedAsyncioTestCase):
    async def test_a_division_move_restarts_the_history(self) -> None:
        # 7-1 and 1st of 8, promoted two divisions, then 4-4 mid-table in the new division.
        scored = await _scored(
            [
                _row(1, JAN, rank=1500, wins=7, losses=1, position=1, teams=8),
                _row(2, FEB, rank=1700, wins=4, losses=4, position=4, teams=8),
            ]
        )
        before, after = scored.loc[101], scored.loc[201]
        self.assertTrue(after["is_changed"])  # precondition: the promotion is a division change

        self.assertGreater(before["linear_stable_shift"], 0.5)
        # The move already paid for the old record: no renewed "+1" on an average showing.
        self.assertLess(abs(after["linear_stable_shift"]), 0.15)
        self.assertEqual(1, after["sample_tournaments"])

    async def test_an_unranked_tournament_does_not_restart_the_history(self) -> None:
        scored = await _scored(
            [
                _row(1, JAN, rank=1500, wins=3, losses=1),
                _row(2, FEB, rank=None, wins=1, losses=3),
                _row(3, MAR, rank=1500, wins=3, losses=1),
            ]
        )

        self.assertEqual([1, 2, 3], scored["sample_tournaments"].tolist())

    async def test_the_evidence_of_a_tournament_grows_with_its_maps(self) -> None:
        scored = await _scored(
            [
                _row(1, JAN, user=1, rank=2500, wins=1, losses=0),
                _row(1, JAN, user=2, rank=2500, wins=20, losses=0),
                # No maps recorded: the match count stands in; nothing at all carries no evidence.
                _row(1, JAN, user=3, rank=2500, wins=0, losses=0, match_count=6),
                _row(1, JAN, user=4, rank=2500, wins=0, losses=0, match_count=0),
            ]
        )

        # coverage 0.7 (no logs) × n/(n + 4)
        self.assertAlmostEqual(0.7 * 1 / 5, scored.loc[101, "effective_evidence"], places=9)
        self.assertAlmostEqual(0.7 * 20 / 24, scored.loc[102, "effective_evidence"], places=9)
        self.assertAlmostEqual(0.7 * 6 / 10, scored.loc[103, "effective_evidence"], places=9)
        self.assertEqual(0.0, scored.loc[104, "effective_evidence"])
        self.assertLess(scored.loc[101, "linear_stable_shift"], scored.loc[102, "linear_stable_shift"])

    async def test_newcomer_flags_do_not_change_linear(self) -> None:
        # The query used to return the roster's newcomer flags, and Linear down-weighted those tournaments by 0.75.
        def history(newcomer: bool) -> list[dict]:
            return [
                _row(1, JAN, rank=2500, wins=3, losses=1, position=2, teams=8, newcomer=newcomer),
                _row(2, FEB, rank=2500, wins=4, losses=0, position=1, teams=8, newcomer=newcomer),
            ]

        veteran, newcomer = await _scored(history(False)), await _scored(history(True))

        for column in ("linear_stable_shift", "linear_trend_shift", "linear_shift_sd", "effective_evidence"):
            with self.subTest(column=column):
                pd.testing.assert_series_equal(veteran[column], newcomer[column])


class LinearShiftSdTests(IsolatedAsyncioTestCase):
    async def test_sd_is_the_posterior_sd_of_the_shrunk_mean(self) -> None:
        # Raw signals ±0.6·0.5 on equal maps: the frame's noise sd is 0.3.
        scored = await _scored(
            [
                _row(1, JAN, user=1, rank=2500, wins=3, losses=1),
                _row(1, JAN, user=2, rank=2500, wins=1, losses=3),
            ]
        )

        evidence = 0.7 * 4 / 8
        expected = ratings.STABLE_SHIFT_SCALE * 0.3 / math.sqrt(1.5 + evidence)
        self.assertAlmostEqual(expected, scored.loc[101, "linear_shift_sd"], places=9)
        self.assertAlmostEqual(expected, scored.loc[102, "linear_shift_sd"], places=9)

    async def test_sd_shrinks_with_evidence(self) -> None:
        scored = await _scored(
            [
                _row(1, JAN, rank=2500, wins=3, losses=1),
                _row(2, FEB, rank=2500, wins=1, losses=3),
                _row(3, MAR, rank=2500, wins=3, losses=1),
            ]
        )

        sds = scored.loc[[101, 201, 301], "linear_shift_sd"].tolist()
        self.assertGreater(sds[0], sds[1])
        self.assertGreater(sds[1], sds[2])

    async def test_sd_is_undefined_without_noise_or_maps(self) -> None:
        constant = await _scored(
            [
                _row(1, JAN, user=1, rank=2500, wins=2, losses=2),
                _row(1, JAN, user=2, rank=2500, wins=1, losses=1),
            ]
        )
        no_maps = await _scored([_row(1, JAN, rank=2500, wins=0, losses=0, match_count=0)])

        self.assertTrue(constant["linear_shift_sd"].isna().all())
        self.assertTrue(no_maps["linear_shift_sd"].isna().all())


class PointsShiftSdTests(IsolatedAsyncioTestCase):
    async def test_sd_sums_the_applied_coefficients_over_the_accumulated_window(self) -> None:
        scored = await _scored(
            [
                # First ranked tournament (0.15), an unchanged regular one that accumulates onto it (0.065), then a
                # promotion that starts a new window (2 × 0.065).
                _row(1, JAN, user=1, rank=1500, wins=3, losses=1),
                _row(2, FEB, user=1, rank=1500, wins=2, losses=2),
                _row(3, MAR, user=1, rank=1700, wins=1, losses=0),
                # Unranked, so still a novice: 0.11.
                _row(1, JAN, user=2, rank=None, wins=2, losses=1),
                _row(1, JAN, user=3, rank=2500, wins=0, losses=0),
            ]
        )

        self.assertAlmostEqual(math.sqrt(0.15**2 * 4), scored.loc[101, "points_shift_sd"], places=9)
        self.assertAlmostEqual(math.sqrt(0.15**2 * 4 + 0.065**2 * 4), scored.loc[201, "points_shift_sd"], places=9)
        self.assertAlmostEqual(math.sqrt(0.13**2 * 1), scored.loc[301, "points_shift_sd"], places=9)
        self.assertAlmostEqual(math.sqrt(0.11**2 * 3), scored.loc[102, "points_shift_sd"], places=9)
        self.assertTrue(pd.isna(scored.loc[103, "points_shift_sd"]))
        # The formula itself is unchanged.
        self.assertEqual([0.3, 0.3, 0.13], scored.loc[[101, 201, 301], "points_shift"].tolist())


def _coarse_grid() -> DivisionGrid:
    """Nine 500-wide tiers over the canonical SR range, the top one open-ended."""
    tiers = tuple(
        DivisionTier(
            id=None,
            slug=f"coarse-{number}",
            number=number,
            name=f"Coarse {number}",
            rank_min=500 + (9 - number) * 500,
            rank_max=None if number == 1 else 500 + (9 - number) * 500 + 499,
            icon_url="",
        )
        for number in range(1, 10)
    )
    return DivisionGrid(version_id=7, tiers=tiers)


class OpenSkillSdTests(TestCase):
    def test_sigma_is_hundredths_of_a_division_on_the_canonical_grid(self) -> None:
        self.assertAlmostEqual(0.5, ratings.rank_sd_to_divisions(DEFAULT_GRID, DEFAULT_GRID, 2500, 50))
        # The open-ended top tier takes its neighbour's width.
        self.assertAlmostEqual(0.5, ratings.rank_sd_to_divisions(DEFAULT_GRID, DEFAULT_GRID, 5600, 50))

    def test_a_coarser_grid_scales_sigma_by_its_tier_width_and_canonical_span(self) -> None:
        canonical_per_tier = (DEFAULT_GRID.max_division - DEFAULT_GRID.min_division) / 8

        self.assertAlmostEqual(
            50 / 500 * canonical_per_tier, ratings.rank_sd_to_divisions(_coarse_grid(), DEFAULT_GRID, 2500, 50)
        )

    def test_a_native_range_tier_converts_through_the_ladder(self) -> None:
        # A 10-wide source tier covering native SR 2000..2999: ten canonical divisions.
        native = DivisionGrid(
            version_id=8,
            tiers=(
                DivisionTier(
                    id=None,
                    slug="n",
                    number=1,
                    name="N",
                    rank_min=0,
                    rank_max=9,
                    icon_url="",
                    native_rank_min=2000,
                    native_rank_max=2999,
                ),
            ),
        )

        self.assertAlmostEqual(2.0, ratings.rank_sd_to_divisions(native, DEFAULT_GRID, 5, 2))


class OpenSkillShiftMapTests(IsolatedAsyncioTestCase):
    async def test_the_map_carries_sigma_in_canonical_divisions(self) -> None:
        df = pd.DataFrame(
            [
                {"tournament_id": 7, "version_id": None, "id_role": "1-tank", "div": 25, "player_id": 12},
                {"tournament_id": 7, "version_id": 7, "id_role": "2-tank", "div": 25, "player_id": 13},
            ]
        )
        rating = SimpleNamespace(mu=2500.0, sigma=50.0)
        service = analytics_flows.analytics_service
        with (
            patch.object(service, "lookback_tournament_ids", AsyncMock(return_value=[7])),
            patch.object(service, "get_matches_for_tournaments", AsyncMock(return_value=[])),
            patch.object(service, "get_teams_with_players", AsyncMock(return_value=[])),
            patch.object(service, "get_rosters", AsyncMock(return_value={})),
            patch.object(analytics_flows, "load_source_grids", AsyncMock(return_value={7: _coarse_grid()})),
            patch.object(
                analytics_flows,
                "prepare_openskill_data",
                return_value=(set(), {"1-tank": rating, "2-tank": rating}, []),
            ),
        ):
            shift_map, _ = await analytics_flows.flows_service.compute_openskill_shift_map(
                SimpleNamespace(), 7, df, workspace_id=1, discipline="overwatch"
            )

        self.assertEqual((0.0, 0.5), shift_map[12])
        self.assertAlmostEqual(ratings.rank_sd_to_divisions(_coarse_grid(), DEFAULT_GRID, 2500, 50), shift_map[13][1])


class CascadeRecalculationTests(IsolatedAsyncioTestCase):
    async def test_later_computed_tournaments_are_rewritten_in_one_commit(self) -> None:
        frame = await _frame(
            [
                _row(tid, started, user=user, rank=2500, wins=wins, losses=4 - wins)
                for tid, started in ((1, JAN), (2, FEB), (3, MAR))
                for user, wins in ((1, 3), (2, 1))
            ]
        )
        added: list[object] = []
        calls: list[str] = []
        session = SimpleNamespace(
            execute=AsyncMock(),
            add=added.append,
            commit=AsyncMock(side_effect=lambda: calls.append("commit")),
        )
        algorithm_ids = {analytics_flows.POINTS: 1, analytics_flows.LINEAR: 2, analytics_flows.OPENSKILL: 3}

        async def ensure_algorithm(session, name):  # noqa: ANN001, ANN202
            calls.append(f"write {name}")
            return SimpleNamespace(id=algorithm_ids[name])

        async def openskill_map(session, tid, df, **kwargs):  # noqa: ANN001, ANN003, ANN202
            return {tid * 100 + 1: (0.5, 0.25)}, True

        later = AsyncMock(return_value=[3])  # tournament 2 was never computed
        openskill = AsyncMock(side_effect=openskill_map)
        with (
            patch.object(analytics_flows, "tournament_discipline", AsyncMock(return_value="overwatch")),
            patch.object(analytics_flows.flows_service, "get_data_frame", AsyncMock(return_value=frame)),
            patch.object(analytics_flows.flows_service, "compute_openskill_shift_map", openskill),
            patch.object(analytics_flows.analytics_service, "computed_tournament_ids_after", later),
            patch.object(analytics_flows.analytics_service, "get_players_by_tournament_id", AsyncMock(return_value=[])),
            patch.object(analytics_flows.analytics_service, "ensure_algorithm", ensure_algorithm),
        ):
            await analytics_flows.flows_service.recalculate_analytics(session, 1, workspace_id=5)

        later.assert_awaited_once_with(session, 1, workspace_id=5, discipline="overwatch")
        self.assertEqual(
            [call(session, tid, frame, workspace_id=5, discipline="overwatch") for tid in (1, 3)],
            openskill.await_args_list,
        )
        players = [row for row in added if isinstance(row, models.AnalyticsPlayer)]
        shifts = [row for row in added if isinstance(row, models.AnalyticsShift)]
        self.assertEqual({1, 3}, {row.tournament_id for row in players})
        players_of = {tid: (tid * 100 + 1, tid * 100 + 2) for tid in (1, 3)}
        self.assertEqual(
            {(tid, algorithm, pid) for tid, pids in players_of.items() for algorithm in (1, 2, 3) for pid in pids},
            {(row.tournament_id, row.algorithm_id, row.player_id) for row in shifts},
        )
        self.assertEqual(1, calls.count("commit"))
        self.assertEqual("commit", calls[-1])

        # Every row carries its algorithm's sd: the frame's for Points/Linear, the replay's for OpenSkill.
        by_key = {(row.tournament_id, row.algorithm_id, row.player_id): row for row in shifts}
        scored = frame.set_index("player_id")
        for tid, (rated, unrated) in players_of.items():
            for pid in (rated, unrated):
                self.assertEqual(round(scored.loc[pid, "points_shift_sd"], 4), by_key[(tid, 1, pid)].shift_sd)
                self.assertEqual(round(scored.loc[pid, "linear_shift_sd"], 4), by_key[(tid, 2, pid)].shift_sd)
            self.assertEqual((0.5, 0.25), (by_key[(tid, 3, rated)].shift, by_key[(tid, 3, rated)].shift_sd))
            # A player the replay did not rate holds: no shift, no sd.
            self.assertEqual((0.0, None), (by_key[(tid, 3, unrated)].shift, by_key[(tid, 3, unrated)].shift_sd))


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` (no async SQLite driver is installed)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement):  # noqa: ANN001, ANN202
        return self._session.execute(statement)


class LaterComputedTournamentsTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tables = (models.Tournament.__table__, models.AnalyticsPlayer.__table__)
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            create_sqlite_tables(conn, tables)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _tournament(self, tid: int, started: datetime, *, workspace: int = 1, computed: bool) -> None:
        self.session.execute(
            sa.insert(models.Tournament.__table__).values(
                id=tid,
                workspace_id=workspace,
                name=f"T{tid}",
                slug=f"t{tid}",
                is_hidden=False,
                start_date=started,
            )
        )
        if computed:
            self.session.execute(
                sa.insert(models.AnalyticsPlayer.__table__).values(
                    id=tid, tournament_id=tid, player_id=tid, wins=0, losses=0
                )
            )

    async def test_chronologically_later_computed_tournaments_of_the_workspace(self) -> None:
        self._tournament(9, JAN, computed=True)  # earlier
        self._tournament(10, FEB, computed=True)  # the recalculated one
        self._tournament(11, APR, computed=True)
        self._tournament(12, MAR, computed=True)  # a lower id is no earlier: chronology decides
        self._tournament(13, MAY, computed=False)  # never computed
        self._tournament(14, JUN, workspace=2, computed=True)  # another workspace

        later = await analytics_service.computed_tournament_ids_after(
            _AsyncSessionShim(self.session), 10, workspace_id=1, discipline="overwatch"
        )

        self.assertEqual([12, 11], later)


def test_recalculation_on_postgres_writes_every_algorithm_and_cascades(stats_parity_database) -> None:
    """The whole recalculation against the migrated schema: algorithm rows on first use, sd columns, the cascade."""
    asyncio.run(_recalculate_on_postgres(*stats_parity_database))


async def _shift_rows(session: AsyncSession) -> dict[tuple[int, str], list[tuple[int, float | None]]]:
    """``{(tournament_id, algorithm): [(row id, shift_sd), ...]}`` of every v1 shift row."""
    rows = await session.execute(
        sa.select(
            models.AnalyticsShift.tournament_id,
            models.AnalyticsAlgorithm.name,
            models.AnalyticsShift.id,
            models.AnalyticsShift.shift_sd,
        ).join(models.AnalyticsAlgorithm, models.AnalyticsAlgorithm.id == models.AnalyticsShift.algorithm_id)
    )
    out: dict[tuple[int, str], list[tuple[int, float | None]]] = {}
    for tournament_id, name, row_id, shift_sd in rows.all():
        out.setdefault((tournament_id, name), []).append((row_id, shift_sd))
    return out


async def _recalculate_on_postgres(url: str, ids: dict[str, int]) -> None:
    # The seed's careers started in this order, all before the tournament and its hidden twin.
    first, never, last = (ids[f"tournament_career_{i}"] for i in (1, 2, 3))
    algorithms = (analytics_flows.POINTS, analytics_flows.LINEAR, analytics_flows.OPENSKILL)
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await analytics_flows.flows_service.recalculate_analytics(session, last, workspace_id=ids["workspace"])
            before = await _shift_rows(session)
            assert {tid for tid, _ in before} == {last}, before.keys()

            with patch.object(session, "commit", AsyncMock(side_effect=session.commit)) as commit:
                await analytics_flows.flows_service.recalculate_analytics(session, first, workspace_id=ids["workspace"])
            after = await _shift_rows(session)
            computed = set(
                await session.scalars(
                    sa.select(models.AnalyticsPlayer.tournament_id).where(
                        models.AnalyticsPlayer.tournament_id.in_([first, never, last])
                    )
                )
            )
    finally:
        await engine.dispose()

    assert commit.await_count == 1
    # The later computed tournament was rewritten; the never-computed one between them was left alone.
    assert computed == {first, last}
    assert set(after) == {(tid, name) for tid in (first, last) for name in algorithms}
    for name in algorithms:
        assert {row_id for row_id, _ in after[(last, name)]}.isdisjoint(row_id for row_id, _ in before[(last, name)])
        assert any(shift_sd is not None for _, shift_sd in after[(first, name)]), name
