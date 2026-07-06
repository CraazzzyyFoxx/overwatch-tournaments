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
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.dialects import postgresql

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

analytics_service = importlib.import_module("src.services.analytics.service")
analytics_read_service = importlib.import_module("src.services.analytics_read.service")
player_profile = importlib.import_module("src.services.ml.features.player_profile")
shift_features = importlib.import_module("src.services.ml.features.shift_features")
mvp_dominance = importlib.import_module("src.services.ml.features.mvp_dominance")
extractors = importlib.import_module("src.services.ml.features.extractors")
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


class GetAnalyticsWindowAndSelfJoinTests(IsolatedAsyncioTestCase):
    """``get_analytics`` is the riskiest shape in the service: two CTEs
    (``player_points_home``/``player_points_away``) grouped by the identity
    column, a self-join of the outer query against both CTEs on that column,
    and two LAG(...) OVER (PARTITION BY ...) window functions."""

    async def test_compiles_and_uses_workspace_member_everywhere(self) -> None:
        session = _CapturingSession()

        await analytics_service.get_analytics(session, workspace_id=1)

        sql = _compiled(session.statements[0])
        # CTEs group by the substitute identity column and still expose it
        # labeled "user_id" for the self-join predicates below.
        self.assertIn(
            "GROUP BY workspace_member.player_id, tournament.player.role, tournament.player.team_id",
            sql,
        )
        # Self-join of the outer query against both home/away CTEs keys off
        # workspace_member.player_id, not the retained FK column.
        self.assertIn(
            "LEFT OUTER JOIN player_points_home ON workspace_member.player_id = player_points_home.user_id",
            sql,
        )
        self.assertIn(
            "LEFT OUTER JOIN player_points_away ON workspace_member.player_id = player_points_away.user_id",
            sql,
        )
        # Window functions partition by the substitute identity column.
        self.assertIn(
            "PARTITION BY workspace_member.player_id, tournament.player.role "
            "ORDER BY tournament.tournament.id) AS previous_cost",
            sql,
        )
        self.assertIn(
            "PARTITION BY workspace_member.player_id, tournament.player.role "
            "ORDER BY tournament.tournament.id) AS pre_previous_cost",
            sql,
        )
        # Outer SELECT still exposes a "user_id" column (frontend/ML readers
        # of get_analytics rows key off row["user_id"]).
        self.assertIn("workspace_member.player_id AS user_id", sql)
        # Final ORDER BY uses the substitute column, same position as before.
        self.assertTrue(
            sql.rstrip().endswith(
                "ORDER BY workspace_member.player_id, tournament.player.role, tournament.tournament.id"
            )
        )
        # performance_points CTE's Player<->MatchStatistics join must route
        # through workspace_member, not the retained Player.user_id column.
        self.assertIn(
            "JOIN matches.statistics ON matches.statistics.user_id = workspace_member.player_id",
            sql,
        )
        # No cartesian/ambiguous-FROM regression: exactly one Player-anchored
        # workspace_member join per CTE/outer-query FROM clause (7 total:
        # points_home, points_away, performance_points CTE, + outer query).
        self.assertEqual(sql.count("JOIN workspace_member ON workspace_member.id"), 4)


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
    """``_player_rank_history`` groups/orders its pandas frame by
    ``(user_id, role)`` downstream -- the SQL-level label and ORDER BY must
    both use the substitute column so the DataFrame column name and sort
    order are unchanged."""

    async def test_query_labels_and_orders_by_workspace_member(self) -> None:
        session = _CapturingSession()

        await shift_features._player_rank_history(session, [1, 2])

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member.player_id AS user_id", sql)
        self.assertTrue("ORDER BY workspace_member.player_id, tournament.player.role, tournament.tournament.id" in sql)


class MvpDominanceJoinTests(IsolatedAsyncioTestCase):
    """``compute_mvp_dominance`` joins ``Player`` to ``MatchStatistics`` on
    identity -- must route through workspace_member with no cartesian
    product introduced by splitting the join predicate across two ON
    clauses."""

    async def test_join_predicate_routes_through_workspace_member(self) -> None:
        session = _CapturingSession()

        await mvp_dominance.compute_mvp_dominance(session, 1)

        sql = _compiled(session.statements[0])
        self.assertIn(
            "JOIN workspace_member ON workspace_member.id = "
            "tournament.player.workspace_member_id AND workspace_member.player_id = "
            "matches.statistics.user_id",
            sql,
        )
        # MatchStatistics.user_id itself (a direct FK, out of scope) is untouched.
        self.assertIn("matches.statistics.user_id", sql)


class ExtractorsJoinTests(IsolatedAsyncioTestCase):
    """``extract_match_features``/``extract_round_residuals`` both join
    ``Player`` to ``MatchStatistics`` on identity + team + tournament; only
    the identity leg moves to workspace_member."""

    async def test_extract_match_features_routes_through_workspace_member(self) -> None:
        session = _CapturingSession()

        await extractors.extract_match_features(session, [1])

        sql = _compiled(session.statements[0])
        self.assertIn(
            "JOIN workspace_member ON workspace_member.id = "
            "tournament.player.workspace_member_id AND workspace_member.player_id = "
            "matches.statistics.user_id",
            sql,
        )
        self.assertIn("tournament.player.team_id = matches.statistics.team_id", sql)

    async def test_extract_round_residuals_routes_through_workspace_member(self) -> None:
        session = _CapturingSession()

        await extractors.extract_round_residuals(session, 1)

        sql = _compiled(session.statements[0])
        self.assertIn(
            "JOIN workspace_member ON workspace_member.id = "
            "tournament.player.workspace_member_id AND workspace_member.player_id = "
            "matches.statistics.user_id",
            sql,
        )


class BacktestRealisedShiftTests(IsolatedAsyncioTestCase):
    """``_realised_shift_map`` labels + orders by the identity column feeding
    the pandas ``groupby(["user_id", "role"])`` shift computation."""

    async def test_query_labels_and_orders_by_workspace_member(self) -> None:
        session = _CapturingSession()

        await backtest._realised_shift_map(session, 1, history_through_tournament_id=5)

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member.player_id AS user_id", sql)
        self.assertIn(
            "ORDER BY workspace_member.player_id, tournament.player.role, tournament.tournament.id",
            sql,
        )
