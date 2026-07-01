"""Tests for player-identity resolution during Google Sheets registration sync.

The bug: ``sync_google_sheet_feed`` created/updated ``BalancerRegistration`` rows
without resolving ``user_id`` (unlike the web form's ``create_registration``,
which calls ``ensure_player_identity``). Without ``user_id`` the OW-rank lookup —
which joins ``overwatch_rank.rank_snapshot`` by ``user_id`` — finds nothing and the
balancer rank-delta UI stays empty.

These tests verify (1) the sync now wires ``ensure_player_identity`` per
registration, and (2) that helper's link-existing / create-new / idempotent
semantics that the fix relies on.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

reg_admin = importlib.import_module("src.services.registration.admin")
reg_service = importlib.import_module("src.services.registration.service")


def _fake_sync_session() -> SimpleNamespace:
    """A session whose queries return no existing binding / no reuse match."""
    result_mock = Mock()
    result_mock.scalars.return_value.all.return_value = []
    result_mock.scalar_one_or_none.return_value = None
    added: list[object] = []
    return SimpleNamespace(
        execute=AsyncMock(return_value=result_mock),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        flush=AsyncMock(),
        add=lambda obj: added.append(obj),
        _added=added,
    )


class SheetSyncIdentityWiringTests(IsolatedAsyncioTestCase):
    async def test_sync_resolves_player_identity_for_each_registration(self) -> None:
        feed = SimpleNamespace(
            id=1,
            source_url="http://sheet.example",
            sheet_id=None,
            gid=None,
            mapping_config_json={"target": 1},
            value_mapping_json={"map": 1},
            header_row_json=None,
            last_synced_at=None,
            last_sync_status=None,
            last_error=None,
        )
        tournament = SimpleNamespace(id=77, workspace_id=1)
        rows = [["BattleTag"], ["Existing#111"]]
        parsed = SimpleNamespace(
            fields={
                "source_record_key": "k1",
                "battle_tag": "Existing#111",
                "display_name": "Existing",
            },
            errors=[],
        )
        session = _fake_sync_session()

        with patch.multiple(
            reg_admin,
            require_google_sheet_feed=AsyncMock(return_value=feed),
            get_tournament_grid=AsyncMock(return_value=Mock()),
            ensure_tournament_exists=AsyncMock(return_value=tournament),
            get_form_custom_field_defs=AsyncMock(return_value=[]),
            fetch_google_sheet_rows=AsyncMock(return_value=rows),
            parse_sheet_row_detailed=Mock(return_value=parsed),
            build_registration_role_payloads=Mock(return_value=[]),
            replace_registration_roles=Mock(),
            serialize_parsed_fields=Mock(return_value={}),
            register_tournament_realtime_update=Mock(),
            ensure_player_identity=AsyncMock(),
        ):
            result = await reg_admin.sync_google_sheet_feed(session, tournament.id)

            reg_admin.ensure_player_identity.assert_awaited_once()
            call_session, call_registration = reg_admin.ensure_player_identity.await_args.args
            self.assertIs(call_session, session)
            self.assertIsInstance(call_registration, reg_admin.models.BalancerRegistration)
            self.assertEqual(call_registration.battle_tag, "Existing#111")

        self.assertEqual(result.created, 1)


class EnsurePlayerIdentitySemanticsTests(IsolatedAsyncioTestCase):
    async def test_links_existing_account_by_battle_tag(self) -> None:
        registration = SimpleNamespace(battle_tag="Existing#111", smurf_tags_json=None, user_id=None)
        existing_user = SimpleNamespace(id=7)
        session = SimpleNamespace(get=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock())

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=existing_user)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 7)
        self.assertEqual(registration.user_id, 7)

    async def test_respects_already_linked_user_id(self) -> None:
        registration = SimpleNamespace(battle_tag="Existing#111", smurf_tags_json=None, user_id=5)
        linked_user = SimpleNamespace(id=5)
        session = SimpleNamespace(get=AsyncMock(return_value=linked_user), add=Mock(), flush=AsyncMock())
        find_mock = AsyncMock()

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", find_mock),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 5)
        self.assertEqual(registration.user_id, 5)
        find_mock.assert_not_awaited()

    async def test_creates_new_player_when_no_match(self) -> None:
        registration = SimpleNamespace(battle_tag="Newbie#222", smurf_tags_json=None, user_id=None)
        added: list[object] = []

        async def _flush() -> None:
            for obj in added:
                if isinstance(obj, reg_service.models.User) and getattr(obj, "id", None) is None:
                    obj.id = 999

        session = SimpleNamespace(
            get=AsyncMock(return_value=None),
            add=lambda obj: added.append(obj),
            flush=AsyncMock(side_effect=_flush),
        )

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=None)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 999)
        self.assertEqual(registration.user_id, 999)

    async def test_creates_new_player_when_no_match_without_auth_user_id_attr(self) -> None:
        """Legacy/sheet-import callers may build a registration stub with no
        ``auth_user_id`` attribute at all; ``ensure_player_identity`` must not
        blow up on ``getattr`` fallback."""
        registration = SimpleNamespace(battle_tag="Newbie#333", smurf_tags_json=None, user_id=None)
        self.assertFalse(hasattr(registration, "auth_user_id"))
        added: list[object] = []

        async def _flush() -> None:
            for obj in added:
                if isinstance(obj, reg_service.models.User) and getattr(obj, "id", None) is None:
                    obj.id = 1000

        session = SimpleNamespace(
            get=AsyncMock(return_value=None),
            add=lambda obj: added.append(obj),
            flush=AsyncMock(side_effect=_flush),
        )

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=None)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 1000)

    async def test_reuses_account_owned_player_over_battle_tag_dedup(self) -> None:
        """Case (a): the auth account already owns a player and the battletag has
        no distinct shadow owner — the account-owned player wins, no collapse."""
        registration = SimpleNamespace(
            battle_tag="AccountOwner#111", smurf_tags_json=None, user_id=None, auth_user_id=42
        )
        owned_user = SimpleNamespace(id=7)
        session = SimpleNamespace(get=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock())

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=owned_user)),
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=owned_user)),
            patch.object(reg_service, "_move_battle_tag_identity", AsyncMock()) as move_mock,
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 7)
        self.assertEqual(registration.user_id, 7)
        move_mock.assert_not_awaited()

    async def test_colliding_shadow_battle_tag_triggers_identity_collapse(self) -> None:
        """Case (b): the auth account owns a player, but a DIFFERENT shadow
        player already holds the battletag — collapse the shadow's battlenet
        identity onto the account-owned player instead of splitting it."""
        registration = SimpleNamespace(
            battle_tag="Shadow#222", smurf_tags_json=None, user_id=None, auth_user_id=42
        )
        owned_user = SimpleNamespace(id=7)
        shadow_user = SimpleNamespace(id=13)
        session = SimpleNamespace(get=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock())

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=owned_user)),
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=shadow_user)),
            patch.object(reg_service, "_move_battle_tag_identity", AsyncMock()) as move_mock,
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 7)
        self.assertEqual(registration.user_id, 7)
        move_mock.assert_awaited_once_with(session, shadow=shadow_user, target=owned_user)

    async def test_shadow_only_no_account_unchanged(self) -> None:
        """Case (c): no auth account owns a player (anonymous/sheet import) —
        behaviour is exactly the pre-existing battletag dedup, unchanged."""
        registration = SimpleNamespace(
            battle_tag="ShadowOnly#333", smurf_tags_json=None, user_id=None, auth_user_id=None
        )
        shadow_user = SimpleNamespace(id=21)
        session = SimpleNamespace(get=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock())

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=None)) as owned_mock,
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=shadow_user)),
            patch.object(reg_service, "_move_battle_tag_identity", AsyncMock()) as move_mock,
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 21)
        self.assertEqual(registration.user_id, 21)
        owned_mock.assert_awaited_once_with(session, None)
        move_mock.assert_not_awaited()

    async def test_creates_new_player_linked_to_auth_account_when_no_match(self) -> None:
        """When neither an owned player nor a battletag match exists, the new
        player is created pre-linked to the registering auth account."""
        registration = SimpleNamespace(
            battle_tag="BrandNew#444", smurf_tags_json=None, user_id=None, auth_user_id=99
        )
        added: list[object] = []

        async def _flush() -> None:
            for obj in added:
                if isinstance(obj, reg_service.models.User) and getattr(obj, "id", None) is None:
                    obj.id = 555

        session = SimpleNamespace(
            get=AsyncMock(return_value=None),
            add=lambda obj: added.append(obj),
            flush=AsyncMock(side_effect=_flush),
        )

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=None)),
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=None)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
        ):
            resolved = await reg_service.ensure_player_identity(session, registration)

        self.assertEqual(resolved, 555)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].auth_user_id, 99)
