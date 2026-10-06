from shared.rbac.catalog import WORKSPACE_SYSTEM_ROLE_NAMES, permission_names_for_workspace_role

#: Every write the referee is meant to hold. The whole point of the role is how
#: short this list is: a grant added to it is a decision, not a side effect.
REFEREE_WRITES = {
    "match.result",
    "registration.update",
    "registration.approve",
    "registration.reject",
    "registration.check_in",
}


def test_referee_writes_are_exactly_results_and_the_registration_queue():
    assert "referee" in WORKSPACE_SYSTEM_ROLE_NAMES
    referee = set(permission_names_for_workspace_role("referee"))
    writes = {name for name in referee if not name.endswith(".read")}
    assert writes == REFEREE_WRITES
    # Everything else it holds is a read an ordinary player already has.
    assert referee - writes == set(permission_names_for_workspace_role("player"))


def test_admin_holds_both_halves_of_each_split():
    admin = set(permission_names_for_workspace_role("admin"))
    assert {"match.update", "match.result", "registration.update", "registration.roles"} <= admin
