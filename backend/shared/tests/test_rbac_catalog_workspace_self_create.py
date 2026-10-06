"""``workspace.self_create`` — the revocable right to bring a workspace into being.

Two properties make it work, and both are easy to break by editing the catalog:
it must BE in the catalog (an operator can only deny a permission that exists as
a row, and rows are upserted from this tuple), and it must stay distinct from the
workspace-scoped ``workspace.create`` grant — denying one must never be denying
the other, since ``AuthUser.is_denied`` matches ``(resource, action)`` exactly.
"""

from shared.rbac.catalog import PERMISSION_CATALOG, permission_names_for_workspace_role


def test_self_create_is_in_the_catalog():
    assert ("workspace", "self_create") in {(p.resource, p.action) for p in PERMISSION_CATALOG}


def test_self_create_is_a_separate_permission_from_the_workspace_scoped_create():
    names = [p.name for p in PERMISSION_CATALOG]
    assert "workspace.self_create" in names
    assert "workspace.create" in names
    assert len(names) == len(set(names))


def test_the_workspace_member_role_confers_no_creation_right():
    """A plain member holds read-only grants; creation is allow-by-default for
    every account and gated only by the deny overlay, never by a role."""
    assert "workspace.self_create" not in permission_names_for_workspace_role("player")
