import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "false"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

from src import schemas  # noqa: E402
from src.core import errors  # noqa: E402
from src.services.team import flows  # noqa: E402


def _team(team_id: int, name: str, balancer_name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=team_id,
        name=name,
        balancer_name=balancer_name or name,
    )


def _participant_row(
    *,
    participant_id: int = 555,
    challonge_id: int = 777,
    group_id: int | None = 10,
    name: str = "External Name",
) -> flows._ChallongeParticipantRow:
    return flows._ChallongeParticipantRow(
        participant_id=participant_id,
        challonge_id=challonge_id,
        source_id=None,
        group_id=group_id,
        group_name="A" if group_id is not None else None,
        challonge_tournament_id=9001,
        name=name,
        active=True,
    )


class ChallongeTeamMappingTests(IsolatedAsyncioTestCase):
    def test_suggestion_normalizes_team_prefix_and_battle_tag(self) -> None:
        index = flows._build_team_suggestion_index([
            _team(42, "Alpha", "Alpha#1234"),
        ])

        self.assertEqual(42, flows._suggest_team_id("Team Alpha#9876", index))

    async def test_sync_creates_explicit_mapping_when_names_differ(self) -> None:
        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        tournament = SimpleNamespace(id=7, name="Tournament 7", groups=[])
        row = _participant_row(name="Totally Different Challonge Name")
        payload = schemas.ChallongeTeamSyncRequest(
            mappings=[
                schemas.ChallongeTeamMapping(
                    participant_id=row.participant_id,
                    group_id=row.group_id,
                    team_id=42,
                )
            ]
        )

        with (
            patch.object(flows.tournament_flows, "get", AsyncMock(return_value=tournament)),
            patch.object(flows.service, "get_by_tournament", AsyncMock(return_value=[_team(42, "Internal")])),
            patch.object(flows, "_fetch_challonge_participant_rows", AsyncMock(return_value=[row])),
            patch.object(flows, "_get_existing_challonge_mappings", AsyncMock(return_value={})),
        ):
            result = await flows.sync_challonge_team_mappings(session, 7, payload)

        added = session.add.call_args.args[0]
        self.assertEqual(row.challonge_id, added.challonge_id)
        self.assertEqual(42, added.team_id)
        self.assertEqual(row.group_id, added.group_id)
        self.assertEqual(7, added.tournament_id)
        self.assertEqual(1, result.created)
        self.assertEqual(0, result.updated)
        self.assertEqual(0, result.unchanged)
        session.commit.assert_awaited_once_with()

    async def test_sync_repeated_mapping_is_unchanged(self) -> None:
        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        tournament = SimpleNamespace(id=7, name="Tournament 7", groups=[])
        row = _participant_row()
        existing = SimpleNamespace(
            challonge_id=row.challonge_id,
            team_id=42,
            group_id=row.group_id,
            tournament_id=7,
        )
        payload = schemas.ChallongeTeamSyncRequest(
            mappings=[
                schemas.ChallongeTeamMapping(
                    participant_id=row.participant_id,
                    group_id=row.group_id,
                    team_id=42,
                )
            ]
        )

        with (
            patch.object(flows.tournament_flows, "get", AsyncMock(return_value=tournament)),
            patch.object(flows.service, "get_by_tournament", AsyncMock(return_value=[_team(42, "Internal")])),
            patch.object(flows, "_fetch_challonge_participant_rows", AsyncMock(return_value=[row])),
            patch.object(
                flows,
                "_get_existing_challonge_mappings",
                AsyncMock(return_value={(row.group_id, row.challonge_id): existing}),
            ),
        ):
            result = await flows.sync_challonge_team_mappings(session, 7, payload)

        session.add.assert_not_called()
        self.assertEqual(1, result.unchanged)
        self.assertEqual(42, existing.team_id)
        session.commit.assert_awaited_once_with()

    async def test_sync_updates_existing_mapping(self) -> None:
        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        tournament = SimpleNamespace(id=7, name="Tournament 7", groups=[])
        row = _participant_row()
        existing = SimpleNamespace(
            challonge_id=row.challonge_id,
            team_id=24,
            group_id=row.group_id,
            tournament_id=7,
        )
        payload = schemas.ChallongeTeamSyncRequest(
            mappings=[
                schemas.ChallongeTeamMapping(
                    participant_id=row.participant_id,
                    group_id=row.group_id,
                    team_id=42,
                )
            ]
        )

        with (
            patch.object(flows.tournament_flows, "get", AsyncMock(return_value=tournament)),
            patch.object(flows.service, "get_by_tournament", AsyncMock(return_value=[_team(42, "Internal")])),
            patch.object(flows, "_fetch_challonge_participant_rows", AsyncMock(return_value=[row])),
            patch.object(
                flows,
                "_get_existing_challonge_mappings",
                AsyncMock(return_value={(row.group_id, row.challonge_id): existing}),
            ),
        ):
            result = await flows.sync_challonge_team_mappings(session, 7, payload)

        session.add.assert_not_called()
        self.assertEqual(42, existing.team_id)
        self.assertEqual(1, result.updated)
        session.commit.assert_awaited_once_with()

    async def test_sync_rejects_team_from_another_tournament(self) -> None:
        session = SimpleNamespace(add=Mock(), commit=AsyncMock())
        tournament = SimpleNamespace(id=7, name="Tournament 7", groups=[])
        row = _participant_row()
        payload = schemas.ChallongeTeamSyncRequest(
            mappings=[
                schemas.ChallongeTeamMapping(
                    participant_id=row.participant_id,
                    group_id=row.group_id,
                    team_id=99,
                )
            ]
        )

        with (
            patch.object(flows.tournament_flows, "get", AsyncMock(return_value=tournament)),
            patch.object(flows.service, "get_by_tournament", AsyncMock(return_value=[_team(42, "Internal")])),
            patch.object(flows, "_fetch_challonge_participant_rows", AsyncMock(return_value=[row])),
        ):
            with self.assertRaises(errors.ApiHTTPException) as raised:
                await flows.sync_challonge_team_mappings(session, 7, payload)

        self.assertEqual(400, raised.exception.status_code)
        self.assertIn("Team 99 does not belong", raised.exception.detail[0]["msg"])
        session.add.assert_not_called()
        session.commit.assert_not_awaited()
