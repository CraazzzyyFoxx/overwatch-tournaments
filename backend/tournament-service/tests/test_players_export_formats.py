"""``GET .../players/export`` serves two formats off one roster read.

``xv-1`` is the solver's input contract and stays the default, so every existing
caller (and the balance-job upload it feeds) is unaffected by ``owt-1`` existing.
The handler's own job is small and entirely about not getting that wrong: pick
the serializer, reject anything else, and hand ``owt-1`` the context the roster
projection cannot know (tournament, roster shape, flex mode, division grid).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent

for candidate in (str(BACKEND_ROOT), str(SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.division_grid import DivisionGrid  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from shared.domain.roster_shape import RosterShape  # noqa: E402
from shared.schemas.identity import PlayerIdentityRead  # noqa: E402
from src.rpc import _helpers as helpers  # noqa: E402
from src.rpc import integrations  # noqa: E402
from src.services.registration import player_export  # noqa: E402
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

SUBJECT = "rpc.tournament.sheet_players_export"
TOURNAMENT_ID = 84
NODE_ID = 12
SHAPE = RosterShape(entries=tuple({"tank": 1, "damage": 2, "support": 2}.items()))
GRID = DivisionGrid(version_id=7, tiers=())


class _FakeResult:
    """Just enough of a SQLAlchemy ``Result`` for a single-row repository read."""

    def __init__(self, row) -> None:
        self._row = row

    def unique(self):
        return self

    def scalars(self):
        return self

    def first(self):
        return self._row


def _roster() -> PlayerRoster:
    return PlayerRoster(
        registration_id=1,
        identity=PlayerIdentityRead(provider="battlenet", handle="player#2100"),
        display_name=None,
        player_id=None,
        auth_user_id=None,
        workspace_member_id=None,
        roles=(
            RosterRole(
                role="tank",
                rank=3100,
                source="registration",
                is_primary=True,
                priority=0,
                subrole="tank_main_tank",
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

        async def fake_for_registration_node(_session, registration_node_id, **_kwargs):
            self.assertEqual(NODE_ID, registration_node_id)
            return {1: _roster()}

        async def fake_node_id(_session, _data, tournament_id):
            self.assertEqual(TOURNAMENT_ID, tournament_id)
            return NODE_ID

        async def fake_shape(_session, _tournament_id):
            return SHAPE

        async def fake_grid(*_args, **_kwargs):
            return GRID

        async def fake_ws_id(_session, _tournament_id):
            return 3

        session = SimpleNamespace(execute=self._fake_execute, add=lambda _row: None)
        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(integrations.auth, "require_tournament_id_permission", fake_permission),
            patch.object(player_export.roster_engine, "for_registration_node", fake_for_registration_node),
            patch.object(integrations, "_registration_node_id", fake_node_id),
            patch.object(player_export, "tournament_slot_shape", fake_shape),
            patch.object(player_export, "get_effective_division_grid", fake_grid),
            # No registration form row -> the flex mode falls back to "optional".
            patch.object(player_export.form_service, "get_form", AsyncMock(return_value=None)),
            patch.object(integrations.auth, "get_tournament_workspace_id", fake_ws_id),
            patch.object(integrations, "quota", SimpleNamespace(charge=AsyncMock())),
        ):
            return await broker.handlers[SUBJECT](
                {"id": TOURNAMENT_ID, "identity": make_identity(), "query": query or {}},
                None,
            )

    async def _fake_execute(self, _query):
        return _FakeResult(SimpleNamespace(id=TOURNAMENT_ID, name="OWT #12", workspace_id=3, discipline="overwatch"))

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
        owt = payload["players"]["1"]["owt"]
        expected_role = {"dimension": "player_role", "role": "tank_main_tank", "parent": "tank"}
        self.assertEqual(expected_role, owt["primary_role"])
        self.assertEqual(expected_role, owt["roles"][0]["role"])
        self.assertNotIn("sub_role", owt)
        self.assertNotIn("subrole", owt["roles"][0])
        self.assertEqual("main_tank", payload["players"]["1"]["stats"]["classes"]["tank"]["subtype"])

    async def test_owt_role_refs_use_the_owner_disciplines_rated_dimension(self) -> None:
        owner = SimpleNamespace(id=TOURNAMENT_ID, name="Arena", workspace_id=3, discipline="arena")
        with (
            patch.object(self, "_fake_execute", AsyncMock(return_value=_FakeResult(owner))),
            patch.object(
                player_export,
                "discipline",
                return_value=SimpleNamespace(rated_dimension=SimpleNamespace(code="position")),
            ) as module,
        ):
            payload = self._result(await self._invoke({"format": ["owt-1"]}))
        module.assert_called_once_with("arena")
        owt = payload["players"]["1"]["owt"]
        self.assertEqual("position", owt["primary_role"]["dimension"])
        self.assertEqual("position", owt["roles"][0]["role"]["dimension"])

    async def test_private_block_needs_the_query_flag(self) -> None:
        without = self._result(await self._invoke({"format": ["owt-1"]}))
        with_flag = self._result(await self._invoke({"format": ["owt-1"], "include_private": ["1"]}))

        self.assertNotIn("private", without["players"]["1"]["owt"])
        self.assertEqual("internal", with_flag["players"]["1"]["owt"]["private"]["admin_notes"])

    async def test_unknown_format_is_rejected(self) -> None:
        envelope = await self._invoke({"format": ["xv-2"]})

        self.assertIsNone(envelope.get("result"))
        self.assertIn("xv-2", envelope["error"]["message"])
