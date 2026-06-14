from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"

team_flows = importlib.import_module("src.services.team.flows")
user_flows = importlib.import_module("src.services.user.flows")


class UserFlowsTests(IsolatedAsyncioTestCase):
    async def test_to_pydantic_includes_requested_identities(self) -> None:
        older = datetime(2024, 1, 1, tzinfo=UTC)
        newer = datetime(2025, 1, 1, tzinfo=UTC)
        user = SimpleNamespace(
            id=7,
            name="Captain",
            avatar_url="https://cdn.example/avatar.png",
            battle_tag=[
                SimpleNamespace(id=10, user_id=7, name="Captain", tag=1234, battle_tag="Captain#1234")
            ],
            discord=[
                SimpleNamespace(id=11, user_id=7, name="old", updated_at=older),
                SimpleNamespace(id=12, user_id=7, name="new", updated_at=newer),
            ],
            twitch=[
                SimpleNamespace(id=13, user_id=7, name="older", updated_at=older),
                SimpleNamespace(id=14, user_id=7, name="newer", updated_at=newer),
            ],
        )

        result = await user_flows.to_pydantic(
            SimpleNamespace(),
            user,
            ["battle_tag", "discord", "twitch"],
        )

        self.assertEqual(7, result.id)
        self.assertEqual("Captain", result.name)
        self.assertEqual("https://cdn.example/avatar.png", result.avatar_url)
        self.assertEqual(["Captain#1234"], [tag.battle_tag for tag in result.battle_tag])
        self.assertEqual(["new", "old"], [discord.name for discord in result.discord])
        self.assertEqual(["newer", "older"], [twitch.name for twitch in result.twitch])

    async def test_team_to_pydantic_can_include_captain(self) -> None:
        captain = SimpleNamespace(
            id=7,
            name="Captain",
            avatar_url=None,
            battle_tag=[
                SimpleNamespace(id=10, user_id=7, name="Captain", tag=1234, battle_tag="Captain#1234")
            ],
            discord=[],
            twitch=[],
        )
        team = SimpleNamespace(
            id=20,
            name="Team",
            avg_sr=2500.0,
            total_sr=15000,
            tournament_id=68,
            captain_id=7,
            tournament=None,
            players=[],
            captain=captain,
            standings=[],
        )

        result = await team_flows.to_pydantic(
            SimpleNamespace(),
            team,
            ["captain", "captain.battle_tag"],
        )

        self.assertEqual("Captain", result.captain.name)
        self.assertEqual(["Captain#1234"], [tag.battle_tag for tag in result.captain.battle_tag])
