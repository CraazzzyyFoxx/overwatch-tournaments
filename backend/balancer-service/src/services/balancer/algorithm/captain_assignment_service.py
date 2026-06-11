from __future__ import annotations

from src.services.balancer.algorithm.entities import Player


def assign_captains(players: list[Player], count: int, mask: dict[str, int] | None = None) -> None:
    """Mark the top-rated players as captains and pin them to a role."""
    active_roles = {role for role, role_count in (mask or {}).items() if role_count > 0} if mask else None

    for player in players:
        player.is_captain = False
        player.captain_role = None

    sorted_players = sorted(
        players,
        key=lambda player: (-player.max_rating, player.uuid),
    )
    for index in range(min(count, len(sorted_players))):
        player = sorted_players[index]
        player.is_captain = True

        pinned_role: str | None = None
        for role in player.preferences:
            if not player.can_play(role):
                continue
            if active_roles is not None and role not in active_roles:
                continue
            pinned_role = role
            break

        if pinned_role is None:
            for role in sorted(player.ratings):
                if active_roles is not None and role not in active_roles:
                    continue
                pinned_role = role
                break

        player.captain_role = pinned_role


class CaptainAssignmentService:
    def assign(self, players: list[Player], captain_count: int, mask: dict[str, int] | None = None) -> None:
        assign_captains(players, captain_count, mask)
