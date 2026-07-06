"""Role-feasibility analysis.

Computes the *structural* minimum number of off-role assignments that any
balancer must produce given a specific player pool. Off-role count alone is a
poor quality signal because some datasets force massive off-roles by their
preference distribution — e.g. only 4 players prefer Support but the mask
demands 12 Support slots. ``FeasibilityReport.structural_min_off_role`` lets
the caller compare the actual result against the theoretical floor.

Off-role definition matches ``result_serializer.teams_to_json``: a player is
off-role when ``not is_flex AND assigned_role != preferences[0]``. Flex
players are never marked off-role.

Approach: bipartite matching with role-slot capacities. Each role has
``mask[role] * num_teams`` slots. A non-flex player has an edge to its 1st
preference slots only. A flex player has edges to all slots of any role it
can play. Maximum matching = max # players placeable WITHOUT being off-role.
``structural_min_off_role = total_slots - max_matching``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from src.services.balancer.algorithm.entities import Player


@dataclass(frozen=True)
class RoleFeasibility:
    role: str
    supply: int  # non-flex players whose 1st preference is this role
    demand: int  # mask[role] * num_teams
    flex_supply: int  # flex players who can play this role


@dataclass(frozen=True)
class FeasibilityReport:
    total_slots: int
    structural_min_off_role: int
    flex_player_count: int
    roles: list[RoleFeasibility] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_slots": self.total_slots,
            "structural_min_off_role": self.structural_min_off_role,
            "flex_player_count": self.flex_player_count,
            "roles": [
                {
                    "role": r.role,
                    "supply": r.supply,
                    "demand": r.demand,
                    "flex_supply": r.flex_supply,
                }
                for r in self.roles
            ],
        }


def analyze_feasibility(
    players: Iterable[Player],
    mask: dict[str, int],
    num_teams: int,
) -> FeasibilityReport:
    role_capacity: dict[str, int] = {role: count * num_teams for role, count in mask.items() if count > 0}
    total_slots = sum(role_capacity.values())

    players_list = list(players)
    supply: dict[str, int] = dict.fromkeys(role_capacity, 0)
    flex_supply: dict[str, int] = dict.fromkeys(role_capacity, 0)
    flex_count = 0

    for player in players_list:
        if player.is_flex:
            flex_count += 1
            for role in role_capacity:
                if role in player.ratings:
                    flex_supply[role] += 1
            continue
        if not player.preferences:
            continue
        first = player.preferences[0]
        if first in role_capacity:
            supply[first] += 1

    matched = _max_no_off_role_matching(players_list, role_capacity)
    structural_min = max(0, total_slots - matched)

    roles = [
        RoleFeasibility(
            role=role,
            supply=supply[role],
            demand=role_capacity[role],
            flex_supply=flex_supply[role],
        )
        for role in sorted(role_capacity)
    ]

    return FeasibilityReport(
        total_slots=total_slots,
        structural_min_off_role=structural_min,
        flex_player_count=flex_count,
        roles=roles,
    )


def _max_no_off_role_matching(
    players: list[Player],
    role_capacity: dict[str, int],
) -> int:
    """Max number of players placeable in a slot that does NOT count as off-role.

    Standard Hungarian-style augmenting-path bipartite matching where each
    role is duplicated into ``role_capacity[role]`` slot nodes.
    """
    slots: list[str] = []
    for role, capacity in role_capacity.items():
        slots.extend([role] * capacity)
    if not slots:
        return 0

    slots_per_role: dict[str, list[int]] = {role: [] for role in role_capacity}
    for slot_idx, role in enumerate(slots):
        slots_per_role[role].append(slot_idx)

    player_eligible: list[list[int]] = []
    for player in players:
        eligible_roles: set[str] = set()
        if player.is_flex:
            for role in role_capacity:
                if role in player.ratings:
                    eligible_roles.add(role)
        elif player.preferences and player.preferences[0] in role_capacity:
            eligible_roles.add(player.preferences[0])
        slot_indices: list[int] = []
        for role in eligible_roles:
            slot_indices.extend(slots_per_role[role])
        player_eligible.append(slot_indices)

    slot_owner: list[int | None] = [None] * len(slots)

    def try_match(player_idx: int, visited: set[int]) -> bool:
        for slot_idx in player_eligible[player_idx]:
            if slot_idx in visited:
                continue
            visited.add(slot_idx)
            owner = slot_owner[slot_idx]
            if owner is None or try_match(owner, visited):
                slot_owner[slot_idx] = player_idx
                return True
        return False

    matched_count = 0
    for player_idx in range(len(players)):
        if try_match(player_idx, set()):
            matched_count += 1
    return matched_count


__all__ = ["FeasibilityReport", "RoleFeasibility", "analyze_feasibility"]
