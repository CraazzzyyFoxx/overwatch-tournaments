"""``GET .../players/export`` serves two formats off one roster read.

``xv-1`` is the solver's input contract and stays the default, so every existing
caller (and the balance-job upload it feeds) is unaffected by ``owt-1`` existing.
The handler's own job is small and entirely about not getting that wrong: pick
the serializer, reject anything else, and hand ``owt-1`` the context the roster
projection cannot know (tournament, roster shape, flex mode, division grid).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent

for candidate in (str(BACKEND_ROOT), str(SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("DEBUG", "false")

from shared.core.enums import HeroClass  # noqa: E402
from shared.division_grid import DivisionGrid  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from src.rpc import _helpers as helpers  # noqa: E402
from src.rpc import integrations  # noqa: E402
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

SUBJECT = "rpc.tournament.sheet_players_export"
TOURNAMENT_ID = 84
SHAPE = parse_roster_slots({"tank": 1, "dps": 2, "support": 2})
GRID = DivisionGrid(version_id=7, tiers=())


def _roster() -> PlayerRoster:
    return PlayerRoster(
        registration_id=1,
        battle_tag="player#2100",
        display_name=None,
        player_id=None,
        auth_user_id=None,
        workspace_member_id=None,
        roles=(
            RosterRole(
                role=HeroClass.tank,
                rank=3100,
                source="registration",
                is_primary=True,
                priority=0,
                subrole=None,
            ),
        ),
        is_full_flex=False,
        admin_notes="internal",
    )


class PlayersExportFormatsTests(IsolatedAsyncioTestCase):
    async def _invoke(self, query: dict[str, list[str]] | None = None) -> dict:
        broker = CapturingBroker()
        integrations.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(SUBJECT, broker.handlers)

        async def fake_permission(*_args, **_kwargs) -> None:
            return None

        async def fake_for_tournament(_session, tournament_id, **_kwargs):
            self.assertEqual(TOURNAMENT_ID, tournament_id)
            return {1: _roster()}

        async def fake_shape(_session, **_kwargs):
            return SHAPE

        async def fake_grid(*_args, **_kwargs):
            return GRID

        session = SimpleNamespace(
            get=self._fake_get,
            scalar=self._fake_scalar,
            add=lambda _row: None,
        )
        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(integrations.auth, "require_tournament_id_permission", fake_permission),
            patch.object(integrations.roster_engine, "for_tournament", fake_for_tournament),
            patch.object(integrations, "get_effective_roster_shape", fake_shape),
            patch.object(integrations, "get_effective_division_grid", fake_grid),
        ):
            return await broker.handlers[SUBJECT](
                {"id": TOURNAMENT_ID, "identity": make_identity(), "query": query or {}},
                None,
            )

    async def _fake_get(self, _model, _pk):
        return SimpleNamespace(id=TOURNAMENT_ID, name="OWT #12", workspace_id=3)

    async def _fake_scalar(self, _query):
        # No registration form row -> the flex mode falls back to "optional".
        return None

    @staticmethod
    def _result(envelope: dict) -> dict:
        return envelope["data"]

    async def test_default_format_is_the_solver_contract(self) -> None:
        payload = self._result(await self._invoke())

        self.assertEqual("xv-1", payload["format"])
        # xv-1 carries nothing but the players; no context leaks into it.
        self.assertIsNone(payload["source"])
        self.assertIsNone(payload["roster"])
        self.assertEqual({"identity", "stats"}, set(payload["players"]["1"]))

    async def test_owt_format_carries_the_roster_shape_and_tournament(self) -> None:
        payload = self._result(await self._invoke({"format": ["owt-1"]}))

        self.assertEqual("owt-1", payload["format"])
        self.assertEqual(SHAPE.slots, payload["roster"]["slots"])
        self.assertEqual("optional", payload["roster"]["flex_role_mode"])
        self.assertEqual(TOURNAMENT_ID, payload["source"]["tournament_id"])
        self.assertEqual("OWT #12", payload["source"]["tournament_name"])
        self.assertEqual(7, payload["source"]["division_grid_version_id"])
        self.assertEqual(3100, payload["players"]["1"]["owt"]["flex_rating"])

    async def test_private_block_needs_the_query_flag(self) -> None:
        without = self._result(await self._invoke({"format": ["owt-1"]}))
        with_flag = self._result(await self._invoke({"format": ["owt-1"], "include_private": ["1"]}))

        self.assertNotIn("private", without["players"]["1"]["owt"])
        self.assertEqual("internal", with_flag["players"]["1"]["owt"]["private"]["admin_notes"])

    async def test_unknown_format_is_rejected(self) -> None:
        envelope = await self._invoke({"format": ["xv-2"]})

        self.assertIsNone(envelope.get("result"))
        self.assertIn("xv-2", envelope["error"]["message"])
