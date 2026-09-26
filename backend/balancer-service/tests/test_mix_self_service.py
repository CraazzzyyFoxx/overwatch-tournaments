"""``mix_self_policy`` -- the fixed order of admission checks for self-signup.

The order is the contract: the FIRST failing check is the reason a client shows,
so a closed mix must never be reported as "link your Battle.net" and a player who
lost a link must still be able to leave. Table-driven over every code in
docs/mix-self-signup-discord/design.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.domain.mix_self_service import MAX_ROSTER, mix_self_policy  # noqa: E402

BOTH = frozenset({"discord", "battlenet"})


def _policy(**overrides):
    kwargs = {
        "status": "draft",
        "self_signup": "pool",
        "self_role_edit": True,
        "on_roster": False,
        "missing_links": frozenset(),
        "has_player": True,
        "self_join_denied": False,
        "roster_size": 0,
    }
    kwargs.update(overrides)
    return mix_self_policy(**kwargs)


def test_an_open_mix_admits_a_fully_linked_newcomer() -> None:
    policy = _policy()
    assert (policy.can_join, policy.join_blocker) == (True, None)
    assert policy.can_leave is False  # not on the roster yet
    assert (policy.can_edit_roles, policy.edit_blocker) == (False, "not_on_roster")


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_a_terminal_mix_refuses_everything(status: str) -> None:
    policy = _policy(status=status, on_roster=True)
    assert (policy.can_join, policy.can_leave, policy.can_edit_roles) == (False, False, False)
    assert (policy.join_blocker, policy.edit_blocker) == ("mix_closed", "mix_closed")


def test_a_closed_mix_outranks_a_missing_link() -> None:
    """Precedence, not a coincidence: telling an unlinked player to link their
    account for a cancelled mix sends them fixing the wrong thing."""
    policy = _policy(status="cancelled", missing_links=BOTH, has_player=False)
    assert (policy.join_blocker, policy.edit_blocker) == ("mix_closed", "mix_closed")


@pytest.mark.parametrize(
    ("missing", "code"),
    [
        (frozenset({"discord"}), "discord_not_linked"),
        (frozenset({"battlenet"}), "battlenet_not_linked"),
        (BOTH, "discord_not_linked"),
    ],
)
def test_a_missing_link_blocks_join_and_edit(missing: frozenset[str], code: str) -> None:
    policy = _policy(missing_links=missing, on_roster=True)
    assert (policy.join_blocker, policy.edit_blocker) == (code, code)
    assert (policy.can_join, policy.can_edit_roles) == (False, False)


def test_leaving_survives_losing_a_link() -> None:
    """Unlinking Battle.net while rostered must not trap somebody in a lineup."""
    assert _policy(missing_links=BOTH, on_roster=True).can_leave is True


def test_no_player_identity_blocks_join_and_edit() -> None:
    policy = _policy(has_player=False, on_roster=True)
    assert (policy.join_blocker, policy.edit_blocker) == ("player_not_linked", "player_not_linked")


def test_a_missing_link_outranks_a_missing_player() -> None:
    policy = _policy(missing_links=frozenset({"battlenet"}), has_player=False)
    assert policy.join_blocker == "battlenet_not_linked"


def test_a_denied_capability_blocks_join_and_edit() -> None:
    policy = _policy(self_join_denied=True, on_roster=True)
    assert (policy.join_blocker, policy.edit_blocker) == ("self_join_denied", "self_join_denied")
    assert policy.can_leave is True


def test_a_seated_player_is_already_joined_and_may_edit() -> None:
    policy = _policy(on_roster=True)
    assert (policy.can_join, policy.join_blocker) == (False, "already_joined")
    assert (policy.can_edit_roles, policy.edit_blocker) == (True, None)


def test_already_joined_outranks_a_closed_signup_window() -> None:
    """A host closing signup must not make a seated player's panel read
    "signup_closed" -- they are in, and leaving still works."""
    policy = _policy(on_roster=True, self_signup="closed")
    assert policy.join_blocker == "already_joined"
    assert policy.can_leave is True


def test_a_closed_signup_window_blocks_a_newcomer() -> None:
    assert _policy(self_signup="closed").join_blocker == "signup_closed"


def test_a_full_roster_blocks_a_newcomer() -> None:
    assert _policy(roster_size=MAX_ROSTER).join_blocker == "roster_full"
    assert _policy(roster_size=MAX_ROSTER - 1).join_blocker is None


def test_a_closed_window_outranks_a_full_roster() -> None:
    assert _policy(self_signup="closed", roster_size=MAX_ROSTER).join_blocker == "signup_closed"


def test_the_hosts_switch_governs_role_edits_only() -> None:
    policy = _policy(on_roster=True, self_role_edit=False)
    assert (policy.can_edit_roles, policy.edit_blocker) == (False, "role_edit_off")
    assert policy.can_leave is True
    assert policy.join_blocker == "already_joined"


def test_not_being_on_the_roster_outranks_the_hosts_switch() -> None:
    policy = _policy(on_roster=False, self_role_edit=False)
    assert policy.edit_blocker == "not_on_roster"
