from __future__ import annotations

import importlib
import os
import sys
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
        user = SimpleNamespace(
            id=7,
            name="Captain",
            avatar_url="https://cdn.example/avatar.png",
            social_accounts=[
                SimpleNamespace(id=10, user_id=7, provider="battlenet", username="Captain#1234", url=None, is_verified=True, is_primary=True),
                SimpleNamespace(id=12, user_id=7, provider="discord", username="captain", url=None, is_verified=False, is_primary=True),
                SimpleNamespace(id=14, user_id=7, provider="twitch", username="captaintv", url=None, is_verified=False, is_primary=True),
            ],
        )

        result = await user_flows.to_pydantic(
            SimpleNamespace(),
            user,
            ["social_accounts"],
        )

        self.assertEqual(7, result.id)
        self.assertEqual("Captain", result.name)
        self.assertEqual("https://cdn.example/avatar.png", result.avatar_url)
        by_provider = {a.provider: a for a in result.social_accounts}
        self.assertEqual("Captain#1234", by_provider["battlenet"].username)
        self.assertTrue(by_provider["battlenet"].is_verified)
        self.assertEqual("captain", by_provider["discord"].username)
        self.assertEqual("captaintv", by_provider["twitch"].username)

    async def test_team_to_pydantic_can_include_captain(self) -> None:
        captain = SimpleNamespace(
            id=7,
            name="Captain",
            avatar_url=None,
            social_accounts=[
                SimpleNamespace(id=10, user_id=7, provider="battlenet", username="Captain#1234", url=None, is_verified=False, is_primary=True),
            ],
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
            ["captain", "captain.social_accounts"],
        )

        self.assertEqual("Captain", result.captain.name)
        self.assertEqual(
            ["Captain#1234"],
            [a.username for a in result.captain.social_accounts if a.provider == "battlenet"],
        )
