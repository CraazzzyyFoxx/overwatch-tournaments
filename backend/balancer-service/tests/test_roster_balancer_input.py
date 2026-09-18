"""``RosterEngine.balancer_input``: the algorithm's payload, from the rosters.

The ``xv-1`` payload used to be assembled in the browser from the admin list,
which is why the algorithm and the draft could disagree about a rank at all.
It is built from the same ``PlayerRoster`` values now, so what is pinned here is
the one rule the algorithm depends on: a role is in ``classes`` (and therefore
``isActive``) exactly when it is PLAYABLE, and a registration with no playable
role is not in the payload at all -- ``Player.can_play`` is ``role in ratings``,
so an ``isActive`` role with a null rank would be an eligible player the solver
then rates at nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.services.roster import roster_engine  # noqa: E402
from tests.factories import roster  # noqa: E402


def test_payload_carries_only_playable_roles_all_active() -> None:
    payload = roster_engine.balancer_input(
        [
            roster(
                7,
                ranks={"damage": 4000, "support": 2800, "tank": None},
                primary="damage",
                battle_tag="Ana#1",
                subroles={"support": "main_heal"},
            )
        ]
    )

    assert payload["format"] == "xv-1"
    classes = payload["players"]["7"]["stats"]["classes"]
    # Tank is declared but unranked: it must not reach the solver as eligible.
    assert set(classes) == {"damage", "support"}
    assert [entry["isActive"] for entry in classes.values()] == [True, True]
    assert classes["damage"] == {"isActive": True, "rank": 4000, "priority": 0, "subtype": None}
    assert classes["support"] == {"isActive": True, "rank": 2800, "priority": 1, "subtype": "main_heal"}


def test_a_registration_with_no_playable_role_is_not_in_the_payload() -> None:
    payload = roster_engine.balancer_input(
        [
            roster(7, ranks={"damage": 3000}),
            roster(8, ranks={"damage": None, "tank": None}),
            roster(9, ranks={}),
        ]
    )

    assert list(payload["players"]) == ["7"]


def test_identity_falls_back_from_battle_tag_to_display_name_to_the_registration() -> None:
    payload = roster_engine.balancer_input(
        [
            roster(7, ranks={"damage": 3000}, battle_tag="Ana#1", display_name="Ana"),
            roster(8, ranks={"damage": 3000}, battle_tag=None, display_name="Nameless"),
            roster(9, ranks={"damage": 3000}, battle_tag=None),
        ]
    )

    assert [payload["players"][uuid]["identity"]["name"] for uuid in ("7", "8", "9")] == [
        "Ana#1",
        "Nameless",
        "registration-9",
    ]


def test_full_flex_is_carried_through_from_the_registration() -> None:
    payload = roster_engine.balancer_input(
        [
            roster(7, ranks={"damage": 3000, "tank": 3000}, flex=True),
            roster(8, ranks={"damage": 3000, "tank": 3000}, flex=False),
        ]
    )

    assert payload["players"]["7"]["identity"]["isFullFlex"] is True
    assert payload["players"]["8"]["identity"]["isFullFlex"] is False


def test_the_uuid_field_is_selectable_so_a_solved_team_maps_back() -> None:
    # The draft solves on registrations, the mix on workspace members: the
    # caller names the field the result's player uuids carry.
    payload = roster_engine.balancer_input(
        [roster(7, ranks={"damage": 3000}, workspace_member_id=42)],
        key="workspace_member_id",
    )

    assert list(payload["players"]) == ["42"]
