"""P5.2e: analytics-service ``Player.user_id`` readers must route through
``Player.workspace_member_id`` -> ``WorkspaceMember.player_id`` instead of the
retained (but no-longer-read-here) ``Player.user_id`` column.

This service was missed by the original identity/workspace refactor recon and
carries the highest-risk query shapes in the whole migration: window
functions with ``partition_by``, a self-join between two CTEs keyed on the
substitute identity column, and multi-column ``GROUP BY``/``ORDER BY``.

These are compile-shape tests (no live DB): they capture the statement each
service function builds and assert (a) it compiles cleanly against the
postgres dialect -- this is what silently breaks when a rewritten query's
FROM-clause inference goes wrong (ambiguous FROM / missing join path /
cartesian product) -- and (b) the ``workspace_member`` table/join actually
appears in the compiled SQL in the expected shape, i.e. the join was not
accidentally dropped or mis-keyed.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.dialects import postgresql

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


analytics_service = importlib.import_module("src.services.analytics.service").analytics_service
analytics_read_service = importlib.import_module("src.services.analytics.read_queries").analytics_read_service
from tests.ow_analytics import module as ow_module  # noqa: E402

player_profile = ow_module("features.player_profile")
shift_features = ow_module("features.shift_features")
backtest = importlib.import_module("src.services.ml.training.backtest")


class _EmptyResult:
    def __iter__(self):
        return iter(())

    def all(self):
        return []

    def mappings(self):
        return self

    def unique(self):
        return self

    def scalars(self):
        return self

    def first(self):
        return None


class _CapturingSession:
    """Fake AsyncSession that records every statement passed to execute()."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _EmptyResult()

    async def scalars(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _EmptyResult()

    async def scalar(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return None


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class GetTeamsWithPlayersEagerLoadTests(IsolatedAsyncioTestCase):
    """``get_teams_with_players`` swaps its dead ``Player.user`` eager-load
    (the loaded object was never read) for ``Player.workspace_member``."""

    async def test_selectinload_targets_workspace_member(self) -> None:
        session = _CapturingSession()

        await analytics_service.get_teams_with_players(session, 1)

        stmt = session.statements[0]
        loader_paths = {
            "-".join(str(p) for p in opt.path.natural_path) for opt in stmt._with_options if hasattr(opt, "path")
        }
        joined = " ".join(loader_paths)
        self.assertIn("workspace_member", joined)
        self.assertNotIn("Player.user)", joined)


class AnalyticsReadStreaksSubqueryTests(IsolatedAsyncioTestCase):
    """``get_streaks`` builds a subquery keyed on the identity column and
    then joins it back to ``Player`` and ``User`` -- both the subquery's own
    join and the outer join must route through workspace_member, and the
    exposed subquery column must stay named ``user_id`` for the outer
    ``subquery.c.user_id`` references."""

    async def test_subquery_and_outer_join_use_workspace_member(self) -> None:
        session = _CapturingSession()

        await analytics_read_service.get_streaks(session, 1)

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member.player_id AS user_id", sql)
        self.assertIn("anon_1.user_id = workspace_member.player_id", sql)
        self.assertIn('JOIN players."user" ON players."user".id = anon_1.user_id', sql)


class PlayerProfileHistoryTests(IsolatedAsyncioTestCase):
    """``load_player_signal_profile``'s base + history queries both label
    the substitute column "user_id" (consumed as a DataFrame column) and the
    history query's ``.in_()``/``order_by`` must use the same substitute."""

    async def test_base_query_labels_workspace_member_as_user_id(self) -> None:
        session = _CapturingSession()

        await player_profile.load_player_signal_profile(session, 1)

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member.player_id AS user_id", sql)
        self.assertIn(
            "JOIN workspace_member ON workspace_member.id = tournament.player.workspace_member_id",
            sql,
        )


class ShiftFeaturesRankHistoryTests(IsolatedAsyncioTestCase):
    """``load_player_rank_history`` groups/orders its pandas frame by
    ``(user_id, role)`` downstream -- the SQL-level label and ORDER BY must
    both use the substitute column so the DataFrame column name and sort
    order are unchanged."""

    async def test_query_labels_and_orders_by_workspace_member(self) -> None:
        session = _CapturingSession()

        await shift_features.load_player_rank_history(session, [1, 2])

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member.player_id AS user_id", sql)
        self.assertRegex(
            sql,
            r"(?s)ORDER BY workspace_member\.player_id, \(SELECT coalesce\(rated_parent\.code, rated_leaf\.code\).*?LIMIT 1\), tournament\.tournament\.id$",
        )


class BacktestRealisedShiftTests(IsolatedAsyncioTestCase):
    """``_realised_shift_map`` labels the identity column feeding the pandas ``groupby(["user_id", "role"])`` shift
    computation (its start-date order is covered by ``test_ml_backtest_scoring``)."""

    async def test_query_labels_by_workspace_member(self) -> None:
        session = _CapturingSession()

        await backtest._realised_shift_map(session, 1, history_through_tournament_id=5, discipline="overwatch")

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member.player_id AS user_id", sql)
