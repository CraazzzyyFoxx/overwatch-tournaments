from shared.rbac.catalog import (
    PERMISSION_CATALOG,
    WORKSPACE_SYSTEM_ROLE_NAMES,
    permission_names_for_workspace_role,
)


def test_player_role_and_self_register():
    assert "player" in WORKSPACE_SYSTEM_ROLE_NAMES
    assert permission_names_for_workspace_role("player") == ()
    assert ("registration", "self_register") in {(p.resource, p.action) for p in PERMISSION_CATALOG}
