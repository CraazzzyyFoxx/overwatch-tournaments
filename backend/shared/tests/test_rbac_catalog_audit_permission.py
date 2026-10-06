from shared.rbac.catalog import PERMISSION_CATALOG, permission_names_for_workspace_role


def test_audit_read_is_in_the_catalog():
    assert ("audit", "read") in {(p.resource, p.action) for p in PERMISSION_CATALOG}


def test_workspace_admin_role_grants_audit_read():
    # `owner` is the `admin.*` wildcard, so it needs no explicit entry; `admin` is an
    # enumerated grant list and would 403 on the audit tab without the catalog entry.
    assert "audit.read" in permission_names_for_workspace_role("admin")
    assert permission_names_for_workspace_role("owner") == ("admin.*",)


def test_player_does_not_get_audit_read():
    # The log carries before/after snapshots of other people's data: it is admin-only
    # even though it is a read. Adding "audit" to _PLAYER_READ_RESOURCES would leak it.
    assert "audit.read" not in permission_names_for_workspace_role("player")
