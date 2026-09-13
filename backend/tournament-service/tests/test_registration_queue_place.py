"""The place a registrant is told they hold.

The counting itself is SQL (``DISTINCT ON`` + ``FILTER``) and is not exercised
here. What is pinned is the mapping around it, where a wrong answer is a number
on a player's own card:

1. a registration that declared no role holds no place in a role queue, and must
   say so rather than report the "1 of 1" an empty count would produce;
2. the role the client labels the numbers with is the one they were counted in,
   not one re-derived from a role list the roster engine may have synthesized.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

service = importlib.import_module("src.services.registration.service")


class _Session:
    """Answers the two statements ``queue_position`` issues, in order."""

    def __init__(self, *, role: str | None, counts: tuple[int, int, int, int]) -> None:
        self._role = role
        self._counts = counts

    async def scalar(self, _statement):
        return self._role

    async def execute(self, _statement):
        return SimpleNamespace(one=lambda: self._counts)


class QueuePlaceTests(IsolatedAsyncioTestCase):
    async def test_reports_the_role_place_beside_the_overall_one(self):
        place = await service.registration_service.queue_position(
            _Session(role="dps", counts=(2, 119, 1, 42)),
            SimpleNamespace(id=7, tournament_id=115, submitted_at=None),
        )

        self.assertEqual((place.position, place.total), (2, 119))
        self.assertEqual((place.role, place.role_position, place.role_total), ("dps", 1, 42))

    async def test_a_registration_with_no_role_holds_no_place_in_a_role_queue(self):
        """The counts come back zero; "0 of 0" and "1 of 1" are both lies."""
        place = await service.registration_service.queue_position(
            _Session(role=None, counts=(2, 119, 0, 0)),
            SimpleNamespace(id=7, tournament_id=115, submitted_at=None),
        )

        self.assertEqual((place.position, place.total), (2, 119))
        self.assertIsNone(place.role)
        self.assertIsNone(place.role_position)
        self.assertIsNone(place.role_total)
