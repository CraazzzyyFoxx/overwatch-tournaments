from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from shared.repository import custom_game


def _session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalars = AsyncMock()
    session.flush = AsyncMock()
    return session


class CustomGameRepositoryTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def test_role_repository_replaces_the_explicit_order(self) -> None:
        session = _session()
        repository = custom_game.CustomGamePlayerRoleRepository()

        await repository.replace_for_player(session, 11, ["support", "tank"])

        session.execute.assert_awaited_once()
        rows = session.add_all.call_args.args[0]
        self.assertEqual(
            [(row.role, row.priority) for row in rows],
            [("support", 1), ("tank", 2)],
        )
        session.flush.assert_awaited_once()

    async def test_co_host_repository_lists_auth_user_ids(self) -> None:
        session = _session()
        session.scalars.return_value = SimpleNamespace(all=lambda: [7, 8])

        result = await custom_game.CustomGameCoHostRepository().user_ids_for_game(session, 11)

        self.assertEqual(result, [7, 8])

    async def test_team_name_repository_returns_an_indexed_mapping(self) -> None:
        session = _session()
        session.execute.return_value = SimpleNamespace(all=lambda: [(0, "Wolves"), (1, "Bears")])

        result = await custom_game.CustomGameTeamNameRepository().mapping_for_game(session, 11)

        self.assertEqual(result, {0: "Wolves", 1: "Bears"})
