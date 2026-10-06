from shared.rbac.catalog import (
    CRUD,
    WORKSPACE_SYSTEM_ROLE_NAMES,
    permission_names_for_workspace_role,
)


def test_host_role_exists_and_gets_full_mix_authorship():
    # `host` is the mix-creator role: membership alone no longer opens mixes
    # (`_require_mix` in balancer-service/src/rpc/custom.py), so a workspace
    # needs a role that grants full CRUD on `custom_game` to actually host one.
    assert "host" in WORKSPACE_SYSTEM_ROLE_NAMES
    host = permission_names_for_workspace_role("host")
    for action in CRUD:
        assert f"custom_game.{action}" in host


def test_host_role_also_keeps_ordinary_player_read_access():
    # A host is still a workspace participant: everything `player` reads
    # (rosters, standings, tournaments, ...) a host reads too.
    player = set(permission_names_for_workspace_role("player"))
    host = set(permission_names_for_workspace_role("host"))
    assert player <= host
    # ...but a host is not a backdoor admin: no write access outside mixes.
    assert "workspace_member.delete" not in host
    assert "tournament.create" not in host
