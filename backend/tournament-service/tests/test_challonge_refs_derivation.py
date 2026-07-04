"""Tests for deriving the KEPT Challonge response fields from the normalized
mapping tables (``shared.services.challonge_refs``) and for the serializers that
consume those derived values instead of the deprecated legacy columns.

These stay DB-free: the resolvers are exercised with a fake session that returns
canned rows, and the serializers are handed prefetched maps directly (the same
contract the flow layer uses to avoid N+1).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest import IsolatedAsyncioTestCase

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

from shared.services import challonge_refs  # noqa: E402

from src import models  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.encounter import flows as encounter_flows  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _FakeSession:
    """Async session stub that returns canned rows and records call count."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.execute_count = 0

    async def execute(self, _query: object) -> _FakeResult:
        self.execute_count += 1
        return _FakeResult(self._rows)


class ResolverTests(IsolatedAsyncioTestCase):
    async def test_empty_ids_short_circuit_without_query(self) -> None:
        session = _FakeSession([])
        self.assertEqual(await challonge_refs.resolve_tournament_challonge(session, []), {})
        self.assertEqual(await challonge_refs.resolve_stage_challonge(session, [None]), {})
        self.assertEqual(await challonge_refs.resolve_encounter_challonge(session, []), {})
        self.assertEqual(session.execute_count, 0)

    async def test_tournament_resolver_maps_id_to_challonge_pair(self) -> None:
        session = _FakeSession([(7, 555, "cup-7")])
        result = await challonge_refs.resolve_tournament_challonge(session, [7])
        self.assertEqual(result, {7: (555, "cup-7")})

    async def test_first_row_wins_on_duplicate(self) -> None:
        # Rows arrive ordered by challonge_source.id asc — the lowest-id row must win.
        session = _FakeSession([(7, 555, "primary"), (7, 999, "shadow")])
        result = await challonge_refs.resolve_tournament_challonge(session, [7])
        self.assertEqual(result, {7: (555, "primary")})

    async def test_stage_resolver_skips_null_stage_ids(self) -> None:
        session = _FakeSession([(None, 1, "x"), (10, 42, "grp")])
        result = await challonge_refs.resolve_stage_challonge(session, [10])
        self.assertEqual(result, {10: (42, "grp")})

    async def test_encounter_resolver_maps_id_to_match_id(self) -> None:
        session = _FakeSession([(100, 9001), (101, 9002)])
        result = await challonge_refs.resolve_encounter_challonge(session, [100, 101])
        self.assertEqual(result, {100: 9001, 101: 9002})


def _tournament() -> models.Tournament:
    return models.Tournament(
        id=1,
        created_at=datetime.now(UTC),
        updated_at=None,
        workspace_id=1,
        number=10,
        name="Tournament 10",
        description=None,
        challonge_id=None,
        challonge_slug=None,
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


def _encounter() -> models.Encounter:
    return models.Encounter(
        id=100,
        created_at=datetime.now(UTC),
        updated_at=None,
        name="Team A vs Team B",
        home_team_id=1,
        away_team_id=2,
        home_score=2,
        away_score=1,
        round=1,
        best_of=3,
        tournament_id=1,
        tournament_group_id=None,
        stage_id=10,
        stage_item_id=20,
        challonge_id=None,
        closeness=None,
        has_logs=False,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.NONE,
        submitted_by_id=None,
        confirmed_by_id=None,
    )


class TournamentDerivationTests(IsolatedAsyncioTestCase):
    async def test_challonge_ref_populates_response_fields(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)

        read = await tournament_flows.to_pydantic(
            cast(AsyncSession, object()),
            tournament,
            [],
            challonge_ref=(321, "great-cup"),
        )

        self.assertEqual(read.challonge_id, 321)
        self.assertEqual(read.challonge_slug, "great-cup")

    async def test_missing_challonge_ref_yields_none_without_query(self) -> None:
        tournament = _tournament()
        make_transient_to_detached(tournament)

        # A fake (non-DB) session must be safe: no prefetch → None, no query.
        read = await tournament_flows.to_pydantic(cast(AsyncSession, object()), tournament, [])

        self.assertIsNone(read.challonge_id)
        self.assertIsNone(read.challonge_slug)

    async def test_group_challonge_ref_populates_fields(self) -> None:
        group = models.TournamentGroup(
            id=3,
            created_at=datetime.now(UTC),
            updated_at=None,
            tournament_id=1,
            name="Group A",
            description=None,
            is_groups=True,
            challonge_id=None,
            challonge_slug=None,
            stage_id=10,
        )
        make_transient_to_detached(group)

        read = await tournament_flows.to_pydantic_group(
            cast(AsyncSession, object()),
            group,
            [],
            challonge_ref=(777, "group-slug"),
        )

        self.assertEqual(read.challonge_id, 777)
        self.assertEqual(read.challonge_slug, "group-slug")


class EncounterDerivationTests(IsolatedAsyncioTestCase):
    async def test_challonge_id_derived_from_match_id_map(self) -> None:
        # Kept transient (not detached): ``encounter.to_dict()`` reads every mapped
        # column, which would lazy-load on a detached instance.
        encounter = _encounter()

        read = await encounter_flows.to_pydantic(
            cast(AsyncSession, object()),
            encounter,
            [],
            challonge_match_ids={100: 8080},
        )

        self.assertEqual(read.challonge_id, 8080)

    async def test_challonge_id_none_when_unmapped(self) -> None:
        encounter = _encounter()

        read = await encounter_flows.to_pydantic(
            cast(AsyncSession, object()),
            encounter,
            [],
            challonge_match_ids={},
        )

        self.assertIsNone(read.challonge_id)
