"""The public ``/users`` overview surface (table, stats KPIs, catalog) must
scope players to the *selected workspace*, which the frontend always passes.

Post identity/workspace refactor, workspace membership is anchored on
``workspace_member.player_id -> players.user.id``. These are compile-shape
tests (no live DB, mirroring the shared ``*_workspace_member`` suites): they
assert ``_apply_workspace_member_filter`` emits the expected correlated EXISTS
against ``workspace_member`` when a workspace id is present, and is a strict
no-op when it is ``None`` (back-compat for callers that don't scope).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from src import models
from src.services.user import service


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_filter_is_noop_when_workspace_id_is_none():
    base = sa.select(models.User.id)
    assert _compiled(service._apply_workspace_member_filter(base, None)) == _compiled(base)


def test_filter_scopes_to_workspace_member_when_id_present():
    base = sa.select(models.User.id)
    sql = _compiled(service._apply_workspace_member_filter(base, 7))

    assert "EXISTS" in sql
    # Correlated on the outer User row via the member's player anchor.
    assert "workspace_member.player_id" in sql
    # Scoped to exactly the requested workspace.
    assert "workspace_member.workspace_id = 7" in sql


def test_count_query_can_be_scoped_the_same_way():
    # get_overview_users applies the filter to both the row query and the
    # distinct-count total query; a count select must accept it too.
    total = sa.select(sa.func.count(sa.distinct(models.User.id)))
    sql = _compiled(service._apply_workspace_member_filter(total, 3))
    assert "count(DISTINCT" in sql
    assert "workspace_member.workspace_id = 3" in sql
