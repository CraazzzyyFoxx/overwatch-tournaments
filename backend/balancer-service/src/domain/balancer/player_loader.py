from __future__ import annotations

import typing

from loguru import logger

from shared.domain.roster_shape import FLEX_SLOT_CODE
from src.domain.balancer.entities import Player
from src.domain.balancer.input_roles import resolve_input_role_name


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
        must_play = bool(identity.get("mustPlay", False))
        rotation_priority = float(identity.get("rotationPriority", 0.0) or 0.0)
        raw_classes = data.get("stats", {}).get("classes", {})
        ratings: dict[str, int] = {}
        role_priorities: list[tuple[int, str]] = []
        subclasses: dict[str, str] = {}

        for json_role, stats in sorted(raw_classes.items()):
            if not stats.get("isActive", False):
                continue
            # ``None`` (an ``owt-1`` declared-but-unranked role that slipped past
            # its ``isActive: false``) reads as unranked, not as a TypeError.
            rank = stats.get("rank") or 0
            if rank <= 0:
                continue
            algorithm_role = resolve_input_role_name(json_role, mask)
            if not algorithm_role:
                continue
            # Roles the roster does not field are kept out of the preference
            # list (nothing can be assigned to them) but stay in ``ratings``:
            # they are what a flex rating is synthesized from, and the saved
            # balance reports them as the player's full ``all_ratings``. ``flex``
            # itself is never a preference -- it is a slot, priced separately.
            ratings[algorithm_role] = rank
            if algorithm_role in mask and algorithm_role != FLEX_SLOT_CODE:
                role_priorities.append((stats.get("priority", 99), algorithm_role))
            subtype = stats.get("subtype") or ""
            if subtype:
                subclasses[algorithm_role] = subtype

        if not ratings:
            return None

        role_priorities.sort(key=lambda item: (item[0], item[1]))
        preferences = [role for _, role in role_priorities]

        if FLEX_SLOT_CODE in mask:
            # A flex slot has no role, so it is worth the best role the player
            # actually plays — the same "ready to play anything" policy the
            # draft applies (see tests/test_forced_flex_parity.py). Taken over
            # the ranks collected above, before this synthesized entry joins
            # them. Being in ``ratings`` is what makes the slot playable and
            # (entities.py / the Rust core) free of discomfort; ``preferences``
            # stays the player's real roles, so ``preferences[0]`` IS their main
            # role everywhere it is read.
            ratings[FLEX_SLOT_CODE] = max(ratings.values())
        elif not preferences:
            # No slot this player can fill: dropped, exactly as before flex
            # slots existed.
            return None

        return Player(
            name,
            ratings,
            preferences,
            uuid,
            mask,
            is_flex=is_flex,
            subclasses=subclasses,
            must_play=must_play,
            rotation_priority=rotation_priority,
        )
    except Exception as exc:
        # One malformed node used to be swallowed into ``None`` -- the run then
        # "succeeded" with a player quietly missing. Surface it: the caller maps
        # ``ValueError`` to a 422 naming the player.
        raise ValueError(f"Failed to parse player {uuid}: {exc}") from exc


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
