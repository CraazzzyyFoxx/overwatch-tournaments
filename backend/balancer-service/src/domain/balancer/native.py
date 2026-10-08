"""Bridge to the ``balancer_native`` extension (``native/balancer_native``).

Both engines share one calling convention, ``run_<engine>(request_json,
progress_callback=None) -> response_json``. Requests share
``{players, num_teams, seed, roles}`` plus the engine's own ``config``;
responses share ``variants[].teams[{id, roster}]`` plus the engine's own
``variants[].metrics``. Each backend supplies only the parts that differ.

``roles`` carries the per-role weights with the roles themselves: the crate has
no role names and no role defaults of its own, so a role's whole meaning to the
engine is what :data:`AlgorithmConfig.role_settings` says here.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

import orjson

from shared.domain.roster_shape import FLEX_SLOT_CODE
from src.domain.balancer.entities import Player, Team
from src.domain.balancer.progress import ProgressCallback
from src.services.balancer.config.defaults import RoleSettings

#: Importable as a plain module once ``maturin develop`` has built the crate.
NATIVE_MODULE = "balancer_native"


def load_native_module():
    try:
        return importlib.import_module(NATIVE_MODULE)
    except ImportError as exc:
        raise RuntimeError(f"Native balancer engines require {NATIVE_MODULE} to be installed") from exc


def build_roles(
    mask: Mapping[str, int],
    role_settings: Mapping[str, RoleSettings],
    project: Callable[[RoleSettings], dict[str, float]],
) -> list[dict[str, Any]]:
    """``role_mask`` -> the engine's ``roles`` list, in mask order.

    Only roles the roster actually fields (``slots > 0``). ``project`` picks the
    settings the calling engine reads, so neither engine sees the other's weights.
    Mask keys may be capitalised (legacy stored masks), role settings never are.
    """
    roles: list[dict[str, Any]] = []
    for name, slots in mask.items():
        if slots <= 0:
            continue
        code = name.lower()
        settings = role_settings.get(code)
        if settings is None:
            raise ValueError(f"no role settings for roster slot '{name}'")
        roles.append({"name": name, "slots": slots, "flex": code == FLEX_SLOT_CODE, **project(settings)})
    return roles


def build_request(
    players: list[Player],
    num_teams: int,
    roles: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    seed: int,
    role_assignment: dict[str, str] | None,
) -> str:
    """The shared request envelope; players sorted by uuid so the same roster
    always reaches the engine in the same order."""
    payload = {
        "players": [
            {
                "uuid": player.uuid,
                "name": player.name,
                "ratings": player.ratings,
                "preferences": player.preferences,
                "subclasses": player.subclasses,
                "is_captain": player.is_captain,
                "is_flex": player.is_flex,
                "seed_role": role_assignment.get(player.uuid) if role_assignment else None,
            }
            for player in sorted(players, key=lambda player: player.uuid)
        ],
        "num_teams": num_teams,
        "seed": seed,
        "roles": roles,
        "config": config,
    }
    return orjson.dumps(payload).decode("utf-8")


def call_engine(function: str, request_json: str, progress_callback: ProgressCallback | None) -> dict[str, Any]:
    engine = getattr(load_native_module(), function)
    if progress_callback is None:
        raw_response = engine(request_json)
    else:
        raw_response = engine(request_json, progress_callback)

    if isinstance(raw_response, bytes):
        raw_response = raw_response.decode("utf-8")
    if not isinstance(raw_response, str):
        raise ValueError(f"{function} returned unsupported response type")
    payload = orjson.loads(raw_response)
    if not isinstance(payload, dict) or not isinstance(payload.get("variants"), list):
        raise ValueError(f"{function} returned invalid payload: missing variants")
    return payload


def deserialize_variants(
    payload: dict[str, Any],
    players: list[Player],
    mask: dict[str, int],
) -> list[tuple[list[Team], dict[str, Any]]]:
    """``variants[]`` -> ``(teams, engine metrics)`` pairs, in engine order."""
    players_by_uuid = {player.uuid: player for player in players}
    variants: list[tuple[list[Team], dict[str, Any]]] = []
    for variant_payload in payload["variants"]:
        if not isinstance(variant_payload, dict):
            continue
        teams_payload = variant_payload.get("teams")
        if not isinstance(teams_payload, list):
            continue

        teams: list[Team] = []
        for team_payload in teams_payload:
            if not isinstance(team_payload, dict):
                continue
            team = Team(int(team_payload.get("id", len(teams) + 1)), mask)
            roster_payload = team_payload.get("roster", {})
            if not isinstance(roster_payload, dict):
                raise ValueError("native engine returned invalid roster payload")
            for role, player_uuids in roster_payload.items():
                if role not in mask or not isinstance(player_uuids, list):
                    continue
                for player_uuid in player_uuids:
                    player = players_by_uuid.get(str(player_uuid))
                    if player is None:
                        raise ValueError(f"native engine referenced unknown player uuid {player_uuid}")
                    team.add_player(role, player)
            teams.append(team)

        if teams:
            metrics = variant_payload.get("metrics")
            variants.append((teams, metrics if isinstance(metrics, dict) else {}))
    return variants


__all__ = [
    "NATIVE_MODULE",
    "build_request",
    "build_roles",
    "call_engine",
    "deserialize_variants",
    "load_native_module",
]
