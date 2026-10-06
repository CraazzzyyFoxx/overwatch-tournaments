from shared.rbac.catalog import (
    PERMISSION_CATALOG,
    WORKSPACE_SYSTEM_ROLE_NAMES,
    permission_names_for_workspace_role,
)


def test_player_is_the_read_only_baseline_role_and_self_register():
    assert "player" in WORKSPACE_SYSTEM_ROLE_NAMES
    assert "member" not in WORKSPACE_SYSTEM_ROLE_NAMES
    player = permission_names_for_workspace_role("player")
    assert "tournament.read" in player
    assert all(name.endswith(".read") for name in player)
    assert ("registration", "self_register") in {(p.resource, p.action) for p in PERMISSION_CATALOG}
