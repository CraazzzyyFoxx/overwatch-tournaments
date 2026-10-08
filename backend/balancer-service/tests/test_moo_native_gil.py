"""Интеграционные тесты нативного balancer_native (MOO): освобождение GIL и валидация входа.

Выполняются только там, где собран нативный модуль (`maturin develop`);
иначе скипаются целиком.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

balancer_native = pytest.importorskip("balancer_native", reason="native balancer_native module is not installed")


def _native_config(generation_count: int = 60, population_size: int = 40) -> dict[str, Any]:
    return {
        "population_size": population_size,
        "generation_count": generation_count,
        "mutation_rate": 0.35,
        "mutation_strength": 2,
        "max_result_variants": 5,
        "average_mmr_balance_weight": 0.8,
        "team_total_balance_weight": 1.0,
        "max_team_gap_weight": 1.5,
        "role_discomfort_weight": 1.0,
        "max_role_discomfort_weight": 2.0,
        "role_line_balance_weight": 1.0,
        "sub_role_collision_weight": 1.5,
        "use_captains": False,
    }


def _roles() -> list[dict[str, Any]]:
    """Slots plus the per-role weights Python owns — the crate has no role defaults."""
    return [
        {"name": name, "slots": slots, "flex": False, "impact": impact, "line_gap_weight": gap, "line_std_weight": std}
        for name, slots, impact, gap, std in (
            ("Tank", 1, 1.4, 0.8, 1.5),
            ("Damage", 2, 1.0, 0.0, 0.0),
            ("Support", 2, 1.1, 0.0, 0.0),
        )
    ]


def _players(num_teams: int) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    index = 0
    for role, capacity in (("Tank", 1), ("Damage", 2), ("Support", 2)):
        for _ in range(capacity * num_teams):
            players.append(
                {
                    "uuid": f"p{index}",
                    "name": f"p{index}",
                    "ratings": {role: 500 + (index * 137) % 1500},
                    "preferences": [role],
                    "subclasses": {},
                    "is_captain": False,
                    "is_flex": False,
                    "seed_role": role,
                }
            )
            index += 1
    return players


def _payload(num_teams: int, *, generation_count: int = 60, drop_players: int = 0) -> str:
    players = _players(num_teams)
    if drop_players:
        players = players[:-drop_players]
    return json.dumps(
        {
            "players": players,
            "num_teams": num_teams,
            "seed": 7,
            "roles": _roles(),
            "config": _native_config(generation_count=generation_count),
        }
    )


def test_event_loop_stays_responsive_during_native_run() -> None:
    """run_moo_optimizer должен отпускать GIL: event loop продолжает крутиться,
    пока оптимизация работает в соседнем потоке через asyncio.to_thread."""

    async def main() -> int:
        ticks = 0
        done = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not done.is_set():
                ticks += 1
                await asyncio.sleep(0.001)

        ticker_task = asyncio.create_task(ticker())
        # Достаточно длинный прогон, чтобы event loop успел сделать десятки тиков
        payload = _payload(8, generation_count=400)
        response = await asyncio.to_thread(balancer_native.run_moo_optimizer, payload)
        done.set()
        await ticker_task
        assert json.loads(response)["variants"], "optimizer must return variants"
        return ticks

    ticks = asyncio.run(main())
    assert ticks >= 5, f"event loop starved during native run (ticks={ticks})"


def test_native_rejects_player_slot_mismatch() -> None:
    """Избыток/недобор игроков должен падать сразу с понятной ошибкой,
    а не молча терять игроков."""
    with pytest.raises(ValueError, match="slots"):
        balancer_native.run_moo_optimizer(_payload(2, drop_players=1))


def test_native_run_is_deterministic() -> None:
    payload = _payload(4)
    first = balancer_native.run_moo_optimizer(payload)
    second = balancer_native.run_moo_optimizer(payload)
    assert first == second
