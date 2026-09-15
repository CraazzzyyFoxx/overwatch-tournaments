"""The admin result RPCs must record the acting *player*, not the auth account.

``tournament.encounter_result_audit.actor_user_id`` is a FK to ``players.user``;
both handlers used to pass ``user.id``, which is an ``auth.user`` id. Two integer
id spaces, one column: the FK stayed satisfied and the name join silently
resolved to whichever unrelated player held that number, so the admin list
credited "Hardstylerz#21775" (player 7) for everything craazzzyyfoxx (auth 7)
confirmed. Nothing failed, which is exactly why this needs a test.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

admin_misc = importlib.import_module("src.rpc.admin_misc")
helpers = importlib.import_module("src.rpc._helpers")
enums = importlib.import_module("shared.core.enums")

AUTH_USER_ID = 7
PLAYER_ID = 599

IDENTITY = make_identity(
    user_id=AUTH_USER_ID,
    workspaces=[
        {
            "workspace_id": 1,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "match", "action": "update"}],
        }
    ],
)


def _settled_encounter() -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.CONFIRMED,
        home_score=3,
        away_score=1,
        closeness=0.7,
        confirmed_at=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
    )


class AdminResultActorIsThePlayerId(IsolatedAsyncioTestCase):
    async def _invoke(self, subject: str, method: str, data: dict, *, player_id: int | None) -> AsyncMock:
        broker = CapturingBroker()
        admin_misc.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        write = AsyncMock(return_value=_settled_encounter())
        resolve = AsyncMock(return_value=player_id)
        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker()))
        self.enterContext(patch.object(admin_misc.auth, "get_encounter_workspace_id", AsyncMock(return_value=1)))
        self.enterContext(patch.object(admin_misc._user_repo, "get_id_by_auth_user_id", resolve))
        self.enterContext(patch.object(admin_misc.captain_service, method, write))
        # The downstream-qualification guard queries a DB this fake has not; the
        # actor attribution under test is independent of it.
        self.enterContext(patch.object(admin_misc, "_assert_source_correction_allowed", AsyncMock()))

        envelope = await broker.handlers[subject](data, None)
        self.assertTrue(envelope.get("ok"), envelope)
        resolve.assert_awaited_once()
        self.assertEqual(AUTH_USER_ID, resolve.await_args.args[1])
        return write

    async def test_confirm_records_the_linked_player_not_the_auth_account(self) -> None:
        write = await self._invoke(
            "rpc.tournament.encounter_set_result",
            "set_encounter_result",
            {"identity": IDENTITY, "id": 10, "payload": {"home_score": 3, "away_score": 1}},
            player_id=PLAYER_ID,
        )

        self.assertEqual(PLAYER_ID, write.await_args.kwargs["actor_user_id"])
        self.assertNotEqual(AUTH_USER_ID, write.await_args.kwargs["actor_user_id"])

    async def test_reopen_records_the_linked_player_not_the_auth_account(self) -> None:
        write = await self._invoke(
            "rpc.tournament.encounter_reopen_result",
            "reopen_encounter_result",
            {"identity": IDENTITY, "id": 10},
            player_id=PLAYER_ID,
        )

        self.assertEqual(PLAYER_ID, write.await_args.kwargs["actor_user_id"])

    async def test_an_account_with_no_linked_player_records_a_machine_actor(self) -> None:
        """NULL reads as "an automated process" in the UI. Writing the auth id
        instead would credit an unrelated player -- worse than saying nothing."""
        write = await self._invoke(
            "rpc.tournament.encounter_set_result",
            "set_encounter_result",
            {"identity": IDENTITY, "id": 10, "payload": {"home_score": 3, "away_score": 1}},
            player_id=None,
        )

        self.assertIsNone(write.await_args.kwargs["actor_user_id"])
