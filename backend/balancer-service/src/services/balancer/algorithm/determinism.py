from __future__ import annotations

import hashlib
import json

from src.services.balancer.config.defaults import AlgorithmConfig
from src.services.balancer.algorithm.entities import Player


def build_balancer_seed(
    players: list[Player],
    num_teams: int,
    config: AlgorithmConfig,
) -> int:
    payload = {
        "config": config.model_dump(),
        "num_teams": num_teams,
        "players": [
            {
                "captain_role": player.captain_role,
                "is_captain": player.is_captain,
                "is_flex": player.is_flex,
                "name": player.name,
                "preferences": list(player.preferences),
                "ratings": player.ratings,
                "subclasses": player.subclasses,
                "uuid": player.uuid,
            }
            for player in sorted(players, key=lambda item: item.uuid)
        ],
    }
    canonical_payload = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def derive_balancer_seed(base_seed: int, label: str) -> int:
    material = f"{base_seed}:{label}".encode()
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big", signed=False)
