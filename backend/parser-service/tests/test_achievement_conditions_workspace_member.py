"""P5.2b: achievement-condition-engine ``Player.user_id`` readers must route
through ``Player.workspace_member_id`` -> ``WorkspaceMember.player_id`` instead
of the retained (but no-longer-read-here) ``Player.user_id`` column.

These are compile-shape tests (no live DB): they capture the statement each
leaf executor builds and assert (a) it compiles cleanly against the postgres
dialect — this is the thing that silently breaks when a rewritten query's
FROM-clause inference goes wrong (ambiguous FROM / missing join path /
cartesian product) — and (b) the ``workspace_member`` table actually appears
in the compiled SQL, i.e. the join was not accidentally dropped.

The highest-risk shapes get dedicated assertions on the *shape* of the SQL
(not just "it compiles"): the ``teammate_recurrence`` self-join (two
``Player`` aliases, each needing its own ``WorkspaceMember`` alias) and the
``Team.captain_id == Player.user_id`` captain-identity join used by both
``is_captain`` and ``captain_property``.
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
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

context_module = importlib.import_module("src.services.achievement.engine.context")
conditions_init = importlib.import_module("src.services.achievement.engine.conditions")
aggregate = importlib.import_module("src.services.achievement.engine.conditions.aggregate")
division = importlib.import_module("src.services.achievement.engine.conditions.division")
player_conditions = importlib.import_module("src.services.achievement.engine.conditions.player")
team_conditions = importlib.import_module("src.services.achievement.engine.conditions.team")
teammate_recurrence = importlib.import_module(
    "src.services.achievement.engine.conditions.teammate_recurrence"
)
tournament_winrate = importlib.import_module(
    "src.services.achievement.engine.conditions.tournament_winrate"
)

EvalContext = context_module.EvalContext


class _EmptyResult:
    def __iter__(self):
        return iter(())

    def all(self):
        return []


class _CapturingSession:
    """Fake AsyncSession that records every statement passed to execute()."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _EmptyResult()


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class GetAllEligibleUsersTests(IsolatedAsyncioTestCase):
    async def test_joins_workspace_member_and_selects_player_id(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        await conditions_init.get_all_eligible_users(session, ctx)

        sql = _compiled(session.statements[0])
        self.assertIn("workspace_member", sql)
        self.assertIn("workspace_member.player_id", sql)
        self.assertIn("workspace_member.id = tournament.player.workspace_member_id", sql)


class IsCaptainConditionTests(IsolatedAsyncioTestCase):
    """``Team.captain_id`` is a FK into the same ``User.id`` identity domain as
    the old ``Player.user_id``; the rewrite must compare it against
    ``WorkspaceMember.player_id`` (the 1:1 substitute), not against
    ``Player.workspace_member_id`` (a different FK/domain)."""

    async def test_compares_captain_id_to_workspace_member_player_id(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        await player_conditions.execute_is_captain(session, {}, ctx)

        sql = _compiled(session.statements[0])
        self.assertIn(
            "tournament.team.captain_id = workspace_member.player_id",
            sql,
        )
        # Must NOT regress to comparing captain_id against the FK column.
        self.assertNotIn("captain_id = tournament.player.workspace_member_id", sql)


class CaptainPropertyConditionTests(IsolatedAsyncioTestCase):
    async def test_captain_subquery_and_teammate_filter_both_use_workspace_member(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        await team_conditions.execute_captain_property(
            session, {"condition": {"type": "is_newcomer", "params": {}}}, ctx
        )

        sql = _compiled(session.statements[0])
        # Captain-matching subquery keys off workspace_member.player_id.
        self.assertIn("tournament.team.captain_id = workspace_member.player_id", sql)
        # Teammate exclusion compares the teammate's identity against the
        # captain subquery's captain_user_id using the same substitute column.
        self.assertIn("workspace_member.player_id != captains.captain_user_id", sql)


class TeammateRecurrenceSelfJoinTests(IsolatedAsyncioTestCase):
    """The riskiest shape in the engine: a self-join of ``Player`` (p1/p2)
    used to detect recurring teammate pairs. Each Player alias needs its own
    WorkspaceMember alias — sharing one alias across both sides would silently
    collapse the pair-detection semantics."""

    async def test_each_player_alias_gets_its_own_workspace_member_alias(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        await teammate_recurrence.execute_teammate_recurrence(session, {}, ctx)

        sql = _compiled(session.statements[0])

        # Two distinct WorkspaceMember aliases, one per Player alias.
        self.assertIn("workspace_member AS wm1", sql)
        self.assertIn("workspace_member AS wm2", sql)
        self.assertIn("wm1.id = p1.workspace_member_id", sql)
        self.assertIn("wm2.id = p2.workspace_member_id", sql)

        # Identity comparisons/grouping use the alias-scoped player_id, not a
        # shared/ambiguous column.
        self.assertIn("least(wm1.player_id, wm2.player_id)", sql)
        self.assertIn("greatest(wm1.player_id, wm2.player_id)", sql)
        self.assertIn("wm1.player_id != wm2.player_id", sql)

    async def test_result_rows_are_still_pairs_of_two_ints(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        result = await teammate_recurrence.execute_teammate_recurrence(session, {}, ctx)

        # Empty result set (no DB), but the leaf must still return the
        # documented ResultSet shape rather than raising.
        self.assertEqual(set(), result)


class DivisionChangeWindowFunctionTests(IsolatedAsyncioTestCase):
    """``div_change`` uses LAG(...) OVER (PARTITION BY user_id, role ...) —
    the partition key must move to workspace_member.player_id and the outer
    subquery must still expose a ``user_id`` column (via .label) since
    downstream code reads ``player_with_lag.c.user_id``."""

    async def test_partition_by_uses_workspace_member_player_id(self) -> None:
        class _FakeGrid:
            pass

        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1, grid=_FakeGrid())

        await division.execute_div_change(session, {"direction": "up", "min_shift": 1}, ctx)

        sql = _compiled(session.statements[0])
        self.assertIn("PARTITION BY workspace_member.player_id", sql)
        # The subquery's exposed column is still named user_id (aliased),
        # so `.c.user_id` downstream keeps working unchanged.
        self.assertIn("workspace_member.player_id AS user_id", sql)


class AggregateDistinctCountRoleTests(IsolatedAsyncioTestCase):
    """distinct_count(field="role") groups by the substitute identity column
    while leaving the unrelated MatchStatistics-based branches (hero/match,
    out of this migration's scope) untouched."""

    async def test_role_branch_groups_by_workspace_member_player_id(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        await aggregate.execute_distinct_count(
            session, {"field": "role", "op": ">=", "value": 1}, ctx
        )

        sql = _compiled(session.statements[0])
        self.assertIn("GROUP BY workspace_member.player_id", sql)


class TournamentWinrateGroupByTests(IsolatedAsyncioTestCase):
    """Multi-column GROUP BY (user, tournament) must swap only the identity
    column and leave tournament_id untouched in the same position."""

    async def test_group_by_keeps_two_columns_with_substituted_identity(self) -> None:
        session = _CapturingSession()
        ctx = EvalContext(workspace_id=1)

        await tournament_winrate.execute_tournament_winrate(
            session, {"op": ">=", "value": 0.5}, ctx
        )

        sql = _compiled(session.statements[0])
        self.assertIn(
            "GROUP BY workspace_member.player_id, tournament.player.tournament_id",
            sql,
        )
