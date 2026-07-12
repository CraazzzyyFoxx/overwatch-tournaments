"""Unit tests for the hidden-tournament visibility rule (pure, no DB).

Full matrix: not-hidden / hidden+anon / hidden+superuser / hidden+ws-admin /
hidden+admin-of-other-ws / hidden+allowlisted / hidden+non-allowlisted.
Mirrors the in-memory AuthUser style of test_auth_user_workspace_deny.py.
"""

from shared.models.identity.auth_user import AuthUser
from shared.models.tournament.tournament import Tournament
from shared.services.tournament_visibility import (
    admin_visible_workspace_ids,
    can_view_tournament,
    visible_tournament_ids_subquery,
)


def _tournament(is_hidden: bool, workspace_id: int = 1) -> Tournament:
    t = Tournament()
    t.id = 100
    t.workspace_id = workspace_id
    t.is_hidden = is_hidden
    return t


def _user(user_id: int, *, superuser: bool = False, ws_admin: list[int] | None = None) -> AuthUser:
    u = AuthUser()
    u.id = user_id
    u.is_superuser = superuser
    u.is_active = True
    ws_admin = ws_admin or []
    ws_rbac = {ws: {"roles": [], "permissions": [{"resource": "*", "action": "*"}]} for ws in ws_admin}
    u.set_rbac_cache(
        role_names=[],
        permissions=[],
        workspaces=[{"workspace_id": w} for w in ws_admin],
        workspace_rbac=ws_rbac,
    )
    return u


def test_not_hidden_visible_to_everyone():
    assert can_view_tournament(None, _tournament(False), set()) is True
    assert can_view_tournament(_user(5), _tournament(False), set()) is True


def test_hidden_hidden_from_anonymous():
    assert can_view_tournament(None, _tournament(True), set()) is False


def test_hidden_visible_to_superuser():
    assert can_view_tournament(_user(5, superuser=True), _tournament(True), set()) is True


def test_hidden_visible_to_workspace_admin():
    assert can_view_tournament(_user(5, ws_admin=[1]), _tournament(True, workspace_id=1), set()) is True


def test_hidden_not_visible_to_admin_of_other_workspace():
    assert can_view_tournament(_user(5, ws_admin=[2]), _tournament(True, workspace_id=1), set()) is False


def test_hidden_visible_to_allowlisted_user():
    assert can_view_tournament(_user(7), _tournament(True), {7}) is True


def test_hidden_not_visible_to_non_allowlisted_logged_in_user():
    assert can_view_tournament(_user(9), _tournament(True), {7}) is False


def test_visible_ids_subquery_excludes_hidden_for_anonymous():
    # The cross-tournament browse/aggregate filter (encounters/matches/teams/
    # stats) reduces to "non-hidden tournaments" for user=None.
    sql = str(
        visible_tournament_ids_subquery(None).compile(compile_kwargs={"literal_binds": True})
    ).lower()
    assert "is_hidden" in sql
    assert "false" in sql


def test_admin_visible_workspace_ids_filters_to_admin_only():
    # Member of ws 1 (admin) and ws 2 (no wildcard) -> only 1 is admin-visible.
    u = AuthUser()
    u.id = 5
    u.is_superuser = False
    u.set_rbac_cache(
        role_names=[],
        permissions=[],
        workspaces=[{"workspace_id": 1}, {"workspace_id": 2}],
        workspace_rbac={1: {"roles": [], "permissions": [{"resource": "*", "action": "*"}]}, 2: {"roles": [], "permissions": []}},
    )
    assert admin_visible_workspace_ids(u) == [1]
