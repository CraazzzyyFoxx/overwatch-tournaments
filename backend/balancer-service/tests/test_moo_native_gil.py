"""Интеграционные тесты нативного moo_core: освобождение GIL и валидация входа.

Выполняются только там, где собран нативный модуль (Linux/Docker);
на остальных платформах скипаются целиком.
"""

from __future__ import annotations

import asyncio
import json
import platform
from typing import Any

import pytest

moo_core = pytest.importorskip("moo_core", reason="native moo_core module is not installed")

pytestmark = pytest.mark.skipif(
    platform.system() != "Linux", reason="Rust MOO backend is Linux-only"
)


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
            "mask": {"Tank": 1, "Damage": 2, "Support": 2},
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
        response = await asyncio.to_thread(moo_core.run_moo_optimizer, payload)
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
        moo_core.run_moo_optimizer(_payload(2, drop_players=1))


def test_native_run_is_deterministic() -> None:
    payload = _payload(4)
    first = moo_core.run_moo_optimizer(payload)
    second = moo_core.run_moo_optimizer(payload)
    assert first == second
