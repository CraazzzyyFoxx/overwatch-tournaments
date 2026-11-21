"""``rpc.balancer.round_teams`` on the real native engine: an individual Swiss round's whole pool comes back as teams of
the roster shape, every id once, and the totals level."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.rpc import round_teams  # noqa: E402

SHAPE = {"tank": 1, "damage": 2, "support": 2}


class _Broker:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def register(handler):
            self.handlers[subject] = handler
            return handler

        return register


def _handler():
    broker = _Broker()
    round_teams.register(broker, logging.getLogger(__name__))
    return broker.handlers[round_teams.SUBJECT]


@unittest.skipUnless(importlib.util.find_spec("balancer_native"), "balancer_native is not installed")
class RoundTeamsRpcTests(unittest.TestCase):
    def test_the_whole_pool_comes_back_as_level_teams_of_the_shape(self) -> None:
        rng = random.Random(7)
        roles = ["tank"] * 8 + ["damage"] * 16 + ["support"] * 16
        players = [{"id": 1000 + i, "role": role, "rank": rng.randint(1500, 4800)} for i, role in enumerate(roles)]
        reply = asyncio.run(_handler()({"discipline": "overwatch", "shape": SHAPE, "players": players}, None))

        self.assertTrue(reply["ok"], reply)
        teams = reply["data"]["teams"]
        self.assertEqual(8, len(teams))
        self.assertEqual(sorted(p["id"] for p in players), sorted(member for team in teams for member in team))
        role_of = {p["id"]: p["role"] for p in players}
        rank_of = {p["id"]: p["rank"] for p in players}
        for team in teams:
            self.assertEqual(SHAPE, dict(Counter(role_of[member] for member in team)))
        totals = [sum(rank_of[member] for member in team) for team in teams]
        # Ranks span 3300: a solver that only shuffled would leave hundreds between teams.
        self.assertLess(max(totals) - min(totals), 150)

    def test_a_pool_that_cannot_fill_the_shape_is_unprocessable(self) -> None:
        players = [{"id": i, "role": "damage", "rank": 2000} for i in range(10)]
        reply = asyncio.run(_handler()({"discipline": "overwatch", "shape": SHAPE, "players": players}, None))
        self.assertEqual((False, "unprocessable"), (reply["ok"], reply["error"]["code"]))
