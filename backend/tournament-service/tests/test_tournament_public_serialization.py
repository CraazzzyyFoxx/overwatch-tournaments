from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from src import models  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.tournament import flows, service  # noqa: E402


def _tournament() -> models.Tournament:
    return models.Tournament(
        id=1,
        created_at=datetime.now(UTC),
        updated_at=None,
        workspace_id=1,
        number=10,
        name="Tournament 10",
        description=None,
        is_league=False,
        is_finished=False,
        status=enums.TournamentStatus.LIVE,
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
        registration_opens_at=None,
        registration_closes_at=None,
        check_in_opens_at=None,
        check_in_closes_at=None,
        win_points=1.0,
        draw_points=0.5,
        loss_points=0.0,
        team_formation="balancer",
        division_grid_version_id=5,
    )


class TournamentSerializationTests(IsolatedAsyncioTestCase):
    async def test_to_pydantic_does_not_touch_unrequested_division_grid_version(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)

        read = await flows.to_pydantic(cast(AsyncSession, object()), tournament, [])

        self.assertEqual(5, read.division_grid_version_id)
        self.assertIsNone(read.division_grid_version)


class TournamentLoadOptionTests(TestCase):
    def test_stages_load_options_stay_summary_only(self) -> None:
        paths = "\n".join(str(getattr(option, "path", "")) for option in service.tournament_entities(["stages"]))

        self.assertIn("Tournament.stages", paths)
        self.assertNotIn("Stage.items", paths)
        self.assertNotIn("StageItem.inputs", paths)

    def test_division_grid_version_is_explicit_load_option(self) -> None:
        paths = "\n".join(
            str(getattr(option, "path", "")) for option in service.tournament_entities(["division_grid_version"])
        )

        self.assertIn("Tournament.division_grid_version", paths)
