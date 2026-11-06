"""Tests for ``create_tournament_from_challonge`` -- the admin orchestrator that
replaces parser-service's old ``tournament.create_with_groups`` bootstrap importer.
Verifies the call sequence (fetch bracket for its name -> create -> link -> import)
and argument passing; the four collaborators it calls are each already covered by
their own tests (create_tournament/update_tournament, challonge_client, challonge sync).
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


admin_tournament = importlib.import_module("src.services.admin.tournament")
challonge_sync = importlib.import_module("src.services.challonge.sync")


class CreateTournamentFromChallongeTests(IsolatedAsyncioTestCase):
    async def test_derives_name_from_challonge_and_links_before_import(self) -> None:
        session = SimpleNamespace(commit=AsyncMock())
        challonge_tournament = SimpleNamespace(id=777, name="Winter Cup", description="desc", url="winter-cup")
        created = SimpleNamespace(id=42)
        finalized = SimpleNamespace(id=42, name="Winter Cup")

        with (
            patch.object(
                admin_tournament.challonge_client, "fetch_tournament", AsyncMock(return_value=challonge_tournament)
            ) as fetch_tournament,
            patch.object(
                admin_tournament.tournament_service, "create_tournament", AsyncMock(return_value=created)
            ) as create,
            patch.object(admin_tournament.tournament_service, "_link_tournament_challonge_source", AsyncMock()) as link,
            patch.object(
                # ``src.services.challonge.sync`` is imported inside
                # ``create_from_challonge``, so the singleton is patched where it
                # lives rather than on the admin module that never binds it.
                challonge_sync.sync_service,
                "import_tournament",
                AsyncMock(return_value={"created": 3}),
            ) as import_,
            patch.object(
                admin_tournament.tournament_service, "get_tournament", AsyncMock(return_value=finalized)
            ) as get,
        ):
            result = await admin_tournament.tournament_service.create_tournament_from_challonge(
                session,
                workspace_id=9,
                discipline="lol",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 2, 1),
                challonge_slug="https://challonge.com/winter-cup",
                division_grid_version_id=None,
            )

        fetch_tournament.assert_awaited_once_with("winter-cup")
        create.assert_awaited_once()
        create_data = create.await_args.args[1]
        self.assertEqual("Winter Cup", create_data.name)
        self.assertEqual("desc", create_data.description)
        self.assertEqual(9, create_data.workspace_id)
        self.assertEqual("lol", create_data.discipline)

        link.assert_awaited_once_with(session, created, challonge_id=777, slug="winter-cup")
        session.commit.assert_awaited_once()
        import_.assert_awaited_once_with(session, 42)
        get.assert_awaited_once_with(session, 42)
        self.assertIs(finalized, result)
