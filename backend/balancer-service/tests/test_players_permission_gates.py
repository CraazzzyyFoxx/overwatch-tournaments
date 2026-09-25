"""``rpc.balancer.players.upsert`` and the ``workspace`` (canon) scope of
``set_ranks`` used to be gated by workspace membership alone: any plain member
could create roster rows or rewrite the shared rank canon every author and
mix inherits, with no ``resource.action`` grant at all -- unlike every sibling
roster-shaping write in this service (``admin.py``, ``binary.py``), which all
require ``team.create``/``team.update``.

``upsert`` additionally admits a mix host (``custom_game.create``): the
add-players dialog exists so a host can type the BattleTag of whoever is in
the lobby, including people the workspace has never seen.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from src.rpc import players  # noqa: E402

WORKSPACE_ID = 9
MEMBER_ID = 77


class _CapturingBroker:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def commit(self) -> None:
        return None


def _identity(role: str, *permissions: tuple[str, str]) -> dict:
    return {
        "user_id": 501,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [
            {
                "workspace_id": WORKSPACE_ID,
                "role": role,
                "rbac_roles": [role],
                "rbac_permissions": [{"resource": resource, "action": action} for resource, action in permissions],
            }
        ],
    }


HOST = _identity("host", ("team", "read"), ("custom_game", "read"), ("custom_game", "create"))
ORGANIZER = _identity("admin", ("team", "read"), ("team", "create"), ("team", "update"))
MEMBER = _identity("member", ("team", "read"), ("custom_game", "read"))


class _GateTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def _call(self, subject: str, identity: dict, **body: object) -> dict:
        broker = _CapturingBroker()
        players.register(broker, _FakeLogger())
        self.ensure = AsyncMock(return_value=SimpleNamespace(id=MEMBER_ID))
        self.set_ranks = AsyncMock(return_value={"tank": 2500})
        row = SimpleNamespace(
            member_id=MEMBER_ID, player_id=1, battle_tag="Newbie#1234", display_name=None, auth_user_id=None
        )
        with (
            patch.object(players, "_SF", _FakeSession),
            patch.object(players.workspace_roster, "ensure_member_for_battle_tag", self.ensure),
            patch.object(players.workspace_roster, "list_roster", AsyncMock(return_value={MEMBER_ID: row})),
            patch.object(players.member_rank_service, "list_layer", AsyncMock(return_value={})),
            patch.object(players.member_rank_service, "set_ranks", self.set_ranks),
            patch.object(players, "emit_pickup_mix_updated", AsyncMock()),
        ):
            data = {"workspace_id": WORKSPACE_ID, "id": MEMBER_ID, "identity": identity, "payload": body}
            return await broker.handlers[subject](data, None)

    def assert_forbidden(self, response: dict) -> None:
        assert response["ok"] is False, response
        assert response["error"]["code"] == "forbidden"


class UpsertPermissionGateTests(_GateTests):
    async def _upsert(self, identity: dict, **body: object) -> dict:
        return await self._call("rpc.balancer.players.upsert", identity, battle_tag="Newbie#1234", **body)

    async def test_mix_host_adds_an_unknown_battle_tag(self) -> None:
        response = await self._upsert(HOST)

        assert response["ok"] is True, response
        assert self.ensure.await_args.kwargs["battle_tag"] == "Newbie#1234"

    async def test_organizer_adds_an_unknown_battle_tag(self) -> None:
        response = await self._upsert(ORGANIZER)

        assert response["ok"] is True, response

    async def test_plain_member_may_not_create_roster_rows(self) -> None:
        self.assert_forbidden(await self._upsert(MEMBER))
        self.ensure.assert_not_awaited()

    async def test_mix_host_may_not_rename_a_roster_row(self) -> None:
        self.assert_forbidden(await self._upsert(HOST, display_name="Somebody else"))
        self.ensure.assert_not_awaited()

    async def test_organizer_renames_a_roster_row(self) -> None:
        response = await self._upsert(ORGANIZER, display_name="Somebody else")

        assert response["ok"] is True, response
        assert self.ensure.await_args.kwargs["display_name"] == "Somebody else"


class SetRanksPermissionGateTests(_GateTests):
    async def _set(self, identity: dict, scope: str) -> dict:
        return await self._call("rpc.balancer.players.set_ranks", identity, scope=scope, ranks={"tank": 2500})

    async def test_writing_the_shared_canon_requires_team_update(self) -> None:
        self.assert_forbidden(await self._set(HOST, "workspace"))
        self.set_ranks.assert_not_awaited()

    async def test_organizer_writes_the_shared_canon(self) -> None:
        response = await self._set(ORGANIZER, "workspace")

        assert response["ok"] is True, response
        assert self.set_ranks.await_args.kwargs["author_user_id"] is None

    async def test_writing_ones_own_book_stays_self_service(self) -> None:
        response = await self._set(MEMBER, "author")

        assert response["ok"] is True, response
        assert self.set_ranks.await_args.kwargs["author_user_id"] == 501
