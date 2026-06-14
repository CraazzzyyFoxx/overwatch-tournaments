from __future__ import annotations

import typing

from loguru import logger

from src.services.balancer.algorithm.input_roles import resolve_input_role_name
from src.services.balancer.algorithm.entities import Player


def parse_player_node(
    uuid: str,
    data: dict[str, typing.Any],
    mask: dict[str, int],
) -> Player | None:
    """Parse player data from an input dictionary."""
    try:
        identity = data.get("identity", {})
        name = identity.get("name", "Unknown")
        is_flex = bool(identity.get("isFullFlex", False))
        raw_classes = data.get("stats", {}).get("classes", {})
        ratings: dict[str, int] = {}
        role_priorities: list[tuple[int, str]] = []
        subclasses: dict[str, str] = {}

        for json_role, stats in sorted(raw_classes.items()):
            if not stats.get("isActive", False):
                continue
            rank = stats.get("rank", 0)
            if rank <= 0:
                continue
            algorithm_role = resolve_input_role_name(json_role, mask)
            if not algorithm_role or algorithm_role not in mask:
                continue
            ratings[algorithm_role] = rank
            role_priorities.append((stats.get("priority", 99), algorithm_role))
            subtype = stats.get("subtype") or ""
            if subtype:
                subclasses[algorithm_role] = subtype

        if not ratings:
            return None

        role_priorities.sort(key=lambda item: (item[0], item[1]))
        preferences = [role for _, role in role_priorities]
        return Player(name, ratings, preferences, uuid, mask, is_flex=is_flex, subclasses=subclasses)
    except Exception as exc:
        logger.warning(f"Failed to parse player {uuid}: {exc}")
        return None


def load_players_from_dict(
    data: dict[str, typing.Any],
    mask: dict[str, int],
) -> list[Player]:
    """Load players from the uploaded payload dictionary."""
    players: list[Player] = []
    try:
        players_dict = data.get("players")

        if not isinstance(players_dict, dict):
            logger.error(f"Could not find players data in input. Available keys: {list(data.keys())}")
            raise ValueError("Could not find players data in input")

        for uuid, player_data in sorted(players_dict.items()):
            player = parse_player_node(uuid, player_data, mask)
            if player is not None:
                players.append(player)

        logger.info(f"Loaded {len(players)} valid players from {len(players_dict)} total")
    except Exception as exc:
        logger.error(f"Error loading players: {exc}")
        raise ValueError(f"Error loading players: {exc}") from exc

    return players
