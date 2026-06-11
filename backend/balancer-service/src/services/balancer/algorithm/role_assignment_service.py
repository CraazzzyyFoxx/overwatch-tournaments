from __future__ import annotations

import random

from loguru import logger

from src.services.balancer.algorithm.entities import Player


def find_feasible_role_assignment(
    players: list[Player],
    num_teams: int,
    mask: dict[str, int],
    rng: random.Random | None = None,
) -> dict[str, str] | None:
    """Find a complete player-to-role assignment that respects role capacities."""
    rng = rng or random
    active_roles = sorted(role for role, count in mask.items() if count > 0)
    active_mask = {role: mask[role] for role in active_roles}
    if not active_mask:
        return None

    capacity = {role: count * num_teams for role, count in active_mask.items()}
    if sum(capacity.values()) != len(players):
        return None

    assignment: dict[int, str] = {}
    role_counts: dict[str, int] = dict.fromkeys(active_mask, 0)
    role_occupants: dict[str, set[int]] = {role: set() for role in active_mask}

    captain_indices: set[int] = set()
    for index, player in enumerate(players):
        if not player.is_captain:
            continue

        captain_indices.add(index)
        role = player.captain_role
        if role is None or role not in active_mask or not player.can_play(role):
            logger.error(
                f"Captain {player.name} (uuid={player.uuid}) has no valid "
                f"captain_role (captain_role={role!r}, can_play={list(player.ratings)}, "
                f"active_mask={list(active_mask)})."
            )
            return None
        if role_counts[role] >= capacity[role]:
            logger.error(
                f"Too many captains pinned to role '{role}': capacity {capacity[role]} "
                f"already filled when placing captain {player.name}."
            )
            return None

        assignment[index] = role
        role_counts[role] += 1
        role_occupants[role].add(index)

    def candidates_for(player: Player) -> list[str]:
        roles = [role for role in active_roles if player.can_play(role)]
        rng.shuffle(roles)
        preference_index = {role: index for index, role in enumerate(player.preferences)}
        roles.sort(key=lambda role: preference_index.get(role, len(player.preferences)))
        return roles

    def try_assign(player_index: int, visited_roles: set[str]) -> bool:
        player = players[player_index]

        for role in candidates_for(player):
            if role in visited_roles:
                continue
            visited_roles.add(role)

            if role_counts[role] < capacity[role]:
                assignment[player_index] = role
                role_counts[role] += 1
                role_occupants[role].add(player_index)
                return True

            occupants = sorted(index for index in role_occupants[role] if index not in captain_indices)
            rng.shuffle(occupants)
            for occupant_index in occupants:
                role_occupants[role].discard(occupant_index)
                del assignment[occupant_index]
                role_counts[role] -= 1

                if try_assign(occupant_index, visited_roles):
                    assignment[player_index] = role
                    role_counts[role] += 1
                    role_occupants[role].add(player_index)
                    return True

                assignment[occupant_index] = role
                role_counts[role] += 1
                role_occupants[role].add(occupant_index)
        return False

    non_captain_order = [index for index in range(len(players)) if index not in captain_indices]
    rng.shuffle(non_captain_order)
    for index in non_captain_order:
        if not try_assign(index, set()):
            return None

    for role, expected in capacity.items():
        if role_counts[role] != expected or len(role_occupants[role]) != expected:
            logger.error(
                f"find_feasible_role_assignment internal invariant violated: "
                f"role={role} counts={role_counts[role]} occupants={len(role_occupants[role])} "
                f"expected={expected}."
            )
            return None

    return {players[index].uuid: role for index, role in assignment.items()}


def diagnose_role_shortage(
    players: list[Player],
    num_teams: int,
    mask: dict[str, int],
) -> dict[str, int]:
    """Return per-role shortages for the requested team count."""
    shortages: dict[str, int] = {}
    for role, count in mask.items():
        if count <= 0:
            continue
        capable = sum(1 for player in players if player.can_play(role))
        needed = count * num_teams
        if capable < needed:
            shortages[role] = needed - capable
    return shortages


class RoleAssignmentService:
    def diagnose_shortage(self, players: list[Player], num_teams: int, mask: dict[str, int]) -> dict[str, int]:
        return diagnose_role_shortage(players, num_teams, mask)

    def find_feasible_assignment(
        self,
        players: list[Player],
        num_teams: int,
        mask: dict[str, int],
    ) -> dict[str, str] | None:
        return find_feasible_role_assignment(players, num_teams, mask)
