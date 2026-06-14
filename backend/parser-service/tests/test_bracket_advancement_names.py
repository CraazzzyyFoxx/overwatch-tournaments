from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

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
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from shared.core import enums  # noqa: E402
from shared.models.encounter_link import EncounterLink  # noqa: E402
from shared.services.bracket import advancement  # noqa: E402


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class BracketAdvancementNameTests(IsolatedAsyncioTestCase):
    async def test_advance_winner_recomputes_target_encounter_name(self) -> None:
        source = SimpleNamespace(
            id=101,
            home_team_id=11,
            away_team_id=22,
            home_score=3,
            away_score=1,
            status=enums.EncounterStatus.COMPLETED,
        )
        target = SimpleNamespace(
            id=202,
            home_team_id=None,
            away_team_id=33,
            name="TBD vs Team Gamma",
        )
        link = EncounterLink(
            source_encounter_id=source.id,
            target_encounter_id=target.id,
            role=enums.EncounterLinkRole.WINNER,
            target_slot=enums.EncounterLinkSlot.HOME,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_ExecuteResult([link])),
            get=AsyncMock(return_value=target),
            flush=AsyncMock(),
        )

        with patch.object(
            advancement,
            "_maybe_create_grand_final_reset",
            AsyncMock(return_value=None),
        ), patch.object(
            advancement,
            "_build_encounter_name_for_ids",
            AsyncMock(return_value="Team Alpha vs Team Gamma"),
        ) as build_name:
            updated = await advancement.advance_winner(session, source)

        self.assertEqual(11, target.home_team_id)
        self.assertEqual(33, target.away_team_id)
        self.assertEqual("Team Alpha vs Team Gamma", target.name)
        self.assertEqual([target], updated)
        build_name.assert_awaited_once_with(
            session,
            home_team_id=11,
            away_team_id=33,
        )
        session.flush.assert_awaited_once_with()
