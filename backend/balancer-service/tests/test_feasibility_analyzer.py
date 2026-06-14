from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from src.services.balancer.algorithm.entities import Player  # noqa: E402
from src.services.balancer.algorithm.feasibility_analyzer import analyze_feasibility  # noqa: E402


MASK = {"Tank": 1, "Damage": 2, "Support": 2}


def make_player(
    uuid: str,
    preferences: list[str],
    extra_roles: list[str] | None = None,
    is_flex: bool = False,
) -> Player:
    """Construct a player whose first preference defines their primary role.

    ``extra_roles`` extends ``ratings`` so the player CAN play those roles
    (used for flex coverage) without listing them as preferences.
    """
    ratings: dict[str, int] = {role: 2000 for role in preferences}
    for role in extra_roles or []:
        ratings.setdefault(role, 1500)
    return Player(
        name=f"P{uuid}",
        ratings=ratings,
        preferences=preferences,
        uuid=uuid,
        mask=MASK,
        is_flex=is_flex,
    )


class TestFeasibilityIdealCases:
    def test_perfect_supply_match_yields_zero_min_off_role(self) -> None:
        # 2 teams, mask 1+2+2 = 10 slots, supply matches demand exactly.
        players = (
            [make_player(f"t{i}", ["Tank"]) for i in range(2)]
            + [make_player(f"d{i}", ["Damage"]) for i in range(4)]
            + [make_player(f"s{i}", ["Support"]) for i in range(4)]
        )
        report = analyze_feasibility(players, MASK, num_teams=2)
        assert report.total_slots == 10
        assert report.structural_min_off_role == 0
        assert report.flex_player_count == 0
        roles = {r.role: r for r in report.roles}
        assert roles["Tank"].supply == 2 and roles["Tank"].demand == 2
        assert roles["Damage"].supply == 4 and roles["Damage"].demand == 4
        assert roles["Support"].supply == 4 and roles["Support"].demand == 4

    def test_oversupply_one_role_undersupply_another(self) -> None:
        # 2 teams, 10 slots. 6 want Tank (only 2 slots), nobody wants Support.
        # Excess Tanks must go off-role; Support slots filled by whoever fits.
        players = (
            [make_player(f"t{i}", ["Tank"]) for i in range(6)]
            + [make_player(f"d{i}", ["Damage"]) for i in range(4)]
        )
        report = analyze_feasibility(players, MASK, num_teams=2)
        assert report.total_slots == 10
        # Max placeable in 1st-pref: 2 Tank + 4 DPS = 6. Remaining 4 slots
        # (all Support) must be filled by off-role players.
        assert report.structural_min_off_role == 4

    def test_no_supply_for_one_role(self) -> None:
        players = (
            [make_player(f"t{i}", ["Tank"]) for i in range(2)]
            + [make_player(f"d{i}", ["Damage"]) for i in range(8)]
        )
        report = analyze_feasibility(players, MASK, num_teams=2)
        # 2 Tank + 4 DPS placeable in 1st pref; 4 Support slots forced off-role.
        assert report.structural_min_off_role == 4


class TestFeasibilityWithFlexPlayers:
    def test_flex_players_fill_gaps_without_off_role(self) -> None:
        # 2 teams = 10 slots. Non-flex supply: 2 Tank, 2 DPS, 2 Sup = 6.
        # Add 4 universally-flex players → they fill remaining 4 slots
        # without being off-role.
        players = (
            [make_player(f"t{i}", ["Tank"]) for i in range(2)]
            + [make_player(f"d{i}", ["Damage"]) for i in range(2)]
            + [make_player(f"s{i}", ["Support"]) for i in range(2)]
            + [
                make_player(
                    f"f{i}", ["Damage"], extra_roles=["Tank", "Support"], is_flex=True
                )
                for i in range(4)
            ]
        )
        report = analyze_feasibility(players, MASK, num_teams=2)
        assert report.flex_player_count == 4
        assert report.structural_min_off_role == 0

    def test_flex_supply_per_role_recorded(self) -> None:
        players = [
            make_player("f1", ["Damage"], extra_roles=["Tank"], is_flex=True),
            make_player("f2", ["Tank"], extra_roles=["Damage", "Support"], is_flex=True),
        ]
        report = analyze_feasibility(players, MASK, num_teams=1)
        roles = {r.role: r for r in report.roles}
        assert roles["Tank"].flex_supply == 2
        assert roles["Damage"].flex_supply == 2
        assert roles["Support"].flex_supply == 1

    def test_flex_players_cannot_fill_role_they_cannot_play(self) -> None:
        # 1 team = 5 slots. 1 Tank, 3 DPS supply, 0 Support supply.
        # Add 1 flex who can play Tank/Damage but NOT Support.
        # Support slots remain forced off-role.
        players = (
            [make_player("t1", ["Tank"])]
            + [make_player(f"d{i}", ["Damage"]) for i in range(3)]
            + [make_player("f1", ["Damage"], extra_roles=["Tank"], is_flex=True)]
        )
        report = analyze_feasibility(players, MASK, num_teams=1)
        # 1 Tank + 2 DPS placed in 1st pref. Flex satisfies remaining DPS slot.
        # Remaining 2 Sup slots cannot be filled by flex → forced off-role.
        assert report.structural_min_off_role == 2


class TestFeasibilityEdgeCases:
    def test_empty_player_list(self) -> None:
        report = analyze_feasibility([], MASK, num_teams=2)
        assert report.total_slots == 10
        assert report.structural_min_off_role == 10  # all slots unfillable
        assert report.flex_player_count == 0

    def test_zero_teams_yields_zero_slots(self) -> None:
        report = analyze_feasibility([], MASK, num_teams=0)
        assert report.total_slots == 0
        assert report.structural_min_off_role == 0

    def test_player_without_preferences_does_not_supply(self) -> None:
        no_pref = Player(
            name="Px", ratings={"Damage": 2000}, preferences=[],
            uuid="x", mask=MASK,
        )
        with_pref = make_player("y", ["Damage"])
        report = analyze_feasibility([no_pref, with_pref], MASK, num_teams=1)
        roles = {r.role: r for r in report.roles}
        # Only one player supplies Damage from preferences[0].
        assert roles["Damage"].supply == 1

    def test_to_dict_shape(self) -> None:
        players = [make_player("t1", ["Tank"]), make_player("d1", ["Damage"])]
        report = analyze_feasibility(players, MASK, num_teams=1)
        d = report.to_dict()
        assert set(d.keys()) == {
            "total_slots",
            "structural_min_off_role",
            "flex_player_count",
            "roles",
        }
        for role_dict in d["roles"]:
            assert set(role_dict.keys()) == {"role", "supply", "demand", "flex_supply"}


class TestFeasibilityRoleSorting:
    def test_roles_returned_in_alphabetical_order(self) -> None:
        report = analyze_feasibility([], MASK, num_teams=1)
        names = [r.role for r in report.roles]
        assert names == sorted(names)
