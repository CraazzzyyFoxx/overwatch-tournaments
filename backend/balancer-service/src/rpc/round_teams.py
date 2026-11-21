"""``rpc.balancer.round_teams``: the teams of one individual Swiss round, formed by the tournament engine.

Internal (no gateway route): tournament-service asks it when it generates a round. Every player arrives with the one
role and rank they play the stage on; the reply is the best variant's teams as lists of the ids it was given, in no
particular order. The ``HIGH_QUALITY`` preset: the roles are fixed, so only the balance axis has anything to weigh.
"""

from __future__ import annotations

import asyncio
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.schemas.rpc import rpc_error, rpc_ok
from src.domain.balancer.runtime import balance_teams
from src.services.balancer.config.provider import get_balancer_config_payload

SUBJECT = "rpc.balancer.round_teams"
#: The solver's own stop; the caller holds a database transaction while it waits.
_TIME_LIMIT_MS = 30_000


def _pool(players: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "players": {
            str(player["id"]): {
                "identity": {"name": str(player["id"])},
                "stats": {
                    "classes": {str(player["role"]): {"isActive": True, "rank": int(player["rank"]), "priority": 1}}
                },
            }
            for player in players
        }
    }


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber(SUBJECT)
    async def _round_teams(data: dict, msg: RabbitMessage) -> dict:
        try:
            discipline = str(data["discipline"])
            shape = {str(role): int(count) for role, count in data["shape"].items()}
            config = {
                **get_balancer_config_payload(discipline)["presets"]["HIGH_QUALITY"],
                "time_limit_ms": _TIME_LIMIT_MS,
            }
            variants = await asyncio.to_thread(
                balance_teams, _pool(data["players"]), config, None, shape, discipline=discipline
            )
        except (KeyError, TypeError, ValueError) as exc:
            return rpc_error("unprocessable", str(exc))
        except Exception:  # pragma: no cover - defensive worker guard
            logger.exception("balancer rpc failed: round_teams")
            return rpc_error("internal", "internal error")
        teams = variants[0]["teams"]
        return rpc_ok(
            {"teams": [[int(p["uuid"]) for seats in team["roster"].values() for p in seats] for team in teams]}
        )
