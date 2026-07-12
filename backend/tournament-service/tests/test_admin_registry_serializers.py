"""Regression: the admin-CRUD serializer ``_ser_player`` must supply the
``grid`` keyword-only argument that ``team_flows.to_pydantic_player`` requires.

A required-kwarg was added to ``to_pydantic_player`` (it resolves
``PlayerRead.division`` against the tournament's effective division grid), but
``_ser_player`` — invoked after ``rpc.tournament.admin.{create,update,delete}``
for the ``player`` entity — was left calling it positionally, so every admin
player write crashed at serialization with::

    TypeError: to_pydantic_player() missing 1 required keyword-only argument: 'grid'

This test drives the REAL ``to_pydantic_player`` (so its signature is enforced)
and asserts ``_ser_player`` resolves the effective grid from the player's
tournament and threads it through.
"""

from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

registry = importlib.import_module("src.services.admin.registry")
team_flows = importlib.import_module("src.services.team.flows")

from shared.division_grid import DEFAULT_GRID  # noqa: E402


def _player() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "id": 1,
            "created_at": None,
            "updated_at": None,
            "name": "Roster Player",
            "sub_role": None,
            "rank": 1500,
            "role": "damage",
            "tournament_id": 78,
            "team_id": 9,
            "is_newcomer": False,
            "is_newcomer_role": False,
            "is_substitution": False,
            "related_player_id": None,
            "workspace_member_id": 555,
        },
        rank=1500,
        tournament_id=78,
        workspace_member=SimpleNamespace(player_id=42, player=SimpleNamespace(id=42)),
        tournament=SimpleNamespace(id=78),
        team=None,
    )


class SerPlayerGridTests(IsolatedAsyncioTestCase):
    async def test_ser_player_resolves_and_passes_effective_grid(self) -> None:
        session = object()
        player = _player()

        fake_user = team_flows.schemas.UserRead(id=42, name="Roster Player")
        get_grid = AsyncMock(return_value=DEFAULT_GRID)

        with (
            patch.object(registry, "get_division_grid", get_grid),
            patch.object(team_flows.user_flows, "to_pydantic", AsyncMock(return_value=fake_user)),
            patch.object(team_flows.tournament_flows, "to_pydantic", AsyncMock(return_value=None)),
        ):
            result = await registry._ser_player(session, player)

        # Grid resolved from the player's own tournament (not global / DEFAULT-by-omission).
        get_grid.assert_awaited_once_with(session, None, tournament_id=78)
        self.assertEqual(42, result["user_id"])
        # division resolved against the effective grid rather than crashing.
        self.assertEqual(DEFAULT_GRID.resolve_division_number(1500), result["division"])
