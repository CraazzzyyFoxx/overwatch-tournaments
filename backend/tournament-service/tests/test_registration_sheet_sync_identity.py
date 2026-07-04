"""Tests for player-identity resolution during Google Sheets registration sync.

The bug: ``sync_google_sheet_feed`` created/updated ``BalancerRegistration`` rows
without resolving the player identity (unlike the web form's
``create_registration``, which calls ``ensure_player_identity``). Without an
identity anchor the OW-rank lookup finds nothing and the balancer rank-delta UI
stays empty. Since dbarch02 dropped ``registration.user_id``, the anchor is
``workspace_member_id`` (member.player_id IS the domain player id).

These tests verify (1) the sync now wires ``ensure_player_identity`` per
registration (passing the tournament's workspace), and (2) that helper's
link-existing / create-new / member-anchoring / idempotent semantics that the
fix relies on.
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

# Patch targets must be the module that OWNS ``sync_google_sheet_feed`` (sheet_sync),
# not the ``admin`` facade: the sync resolves its collaborators (fetch, parse,
# ensure_player_identity, ...) from sheet_sync's module globals.
reg_admin = importlib.import_module("src.services.registration.sheet_sync")
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
            # The sync passes the tournament's workspace so the member anchor
            # is created in the right workspace without an extra query.
            self.assertEqual(
                reg_admin.ensure_player_identity.await_args.kwargs.get("workspace_id"),
                tournament.workspace_id,
            )

        self.assertEqual(result.created, 1)


_WORKSPACE_ID = 1
_MEMBER_ID = 501


def _reg_stub(
    battle_tag: str | None,
    *,
    workspace_member_id: int | None = None,
) -> SimpleNamespace:
    """A registration stub mirroring the ORM row: no user_id column (dropped
    by dbarch02); identity is the ``workspace_member_id`` anchor."""
    return SimpleNamespace(
        id=321,
        tournament_id=77,
        battle_tag=battle_tag,
        smurf_tags_json=None,
        workspace_member_id=workspace_member_id,
        deleted_at=None,
    )


def _identity_session(
    *,
    added: list[object] | None = None,
    get: AsyncMock | None = None,
) -> SimpleNamespace:
    """Session stub for ensure_player_identity: ``scalar`` serves the
    live-collision EXISTS guard in _anchor_registration_member (no collision)."""
    added_list = [] if added is None else added

    async def _flush() -> None:
        for obj in added_list:
            if isinstance(obj, reg_service.models.User) and getattr(obj, "id", None) is None:
                obj.id = 999

    return SimpleNamespace(
        get=get or AsyncMock(return_value=None),
        add=lambda obj: added_list.append(obj),
        flush=AsyncMock(side_effect=_flush),
        scalar=AsyncMock(return_value=False),
        _added=added_list,
    )


def _member_anchor_patch() -> AsyncMock:
    return AsyncMock(return_value=SimpleNamespace(id=_MEMBER_ID, player_id=None))


class EnsurePlayerIdentitySemanticsTests(IsolatedAsyncioTestCase):
    async def test_links_existing_account_by_battle_tag(self) -> None:
        registration = _reg_stub("Existing#111")
        existing_user = SimpleNamespace(id=7)
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=existing_user)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        # The registration is anchored on the player's member row for the
        # right workspace + player (member.player_id IS the domain player id).
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=7)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)

    async def test_respects_already_anchored_member(self) -> None:
        member = SimpleNamespace(id=10, player_id=5)
        linked_user = SimpleNamespace(id=5)
        registration = _reg_stub("Existing#111", workspace_member_id=10)

        async def _get(model, pk):
            if model is reg_service.models.WorkspaceMember:
                self.assertEqual(pk, 10)
                return member
            return linked_user

        session = _identity_session(get=AsyncMock(side_effect=_get))
        find_mock = AsyncMock()

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", find_mock),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 5)
        self.assertEqual(registration.workspace_member_id, 10)
        find_mock.assert_not_awaited()
        # Already anchored on the same player: no member churn.
        member_mock.assert_not_awaited()

    async def test_creates_new_player_when_no_match(self) -> None:
        registration = _reg_stub("Newbie#222")
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=None)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 999)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=999)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)

    async def test_creates_new_player_when_no_match_without_auth_user_id_attr(self) -> None:
        """Legacy/sheet-import callers may build a registration stub with no
        ``auth_user_id`` attribute at all (mirrors the ORM row, which no longer has
        this column); ``ensure_player_identity`` must not blow up when the caller
        also omits the explicit ``auth_user_id`` argument (defaults to ``None``)."""
        registration = _reg_stub("Newbie#333")
        self.assertFalse(hasattr(registration, "auth_user_id"))
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=None)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()),
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 999)

    async def test_reuses_account_owned_player_over_battle_tag_dedup(self) -> None:
        """Case (a): the auth account already owns a player and the battletag has
        no distinct shadow owner — the account-owned player wins, no collapse."""
        registration = _reg_stub("AccountOwner#111")
        owned_user = SimpleNamespace(id=7)
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=owned_user)),
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=owned_user)),
            patch.object(reg_service, "_move_battle_tag_identity", AsyncMock()) as move_mock,
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, auth_user_id=42, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=7)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)
        move_mock.assert_not_awaited()

    async def test_colliding_shadow_battle_tag_triggers_identity_collapse(self) -> None:
        """Case (b): the auth account owns a player, but a DIFFERENT shadow
        player already holds the battletag — collapse the shadow's battlenet
        identity onto the account-owned player instead of splitting it."""
        registration = _reg_stub("Shadow#222")
        owned_user = SimpleNamespace(id=7)
        shadow_user = SimpleNamespace(id=13)
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=owned_user)),
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=shadow_user)),
            patch.object(reg_service, "_move_battle_tag_identity", AsyncMock()) as move_mock,
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, auth_user_id=42, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=7)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)
        move_mock.assert_awaited_once_with(session, shadow=shadow_user, target=owned_user)

    async def test_shadow_only_no_account_unchanged(self) -> None:
        """Case (c): no auth account owns a player (anonymous/sheet import) —
        behaviour is exactly the pre-existing battletag dedup, plus the member
        anchor for the resolved shadow player."""
        registration = _reg_stub("ShadowOnly#333")
        shadow_user = SimpleNamespace(id=21)
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=None)) as owned_mock,
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=shadow_user)),
            patch.object(reg_service, "_move_battle_tag_identity", AsyncMock()) as move_mock,
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, auth_user_id=None, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 21)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=21)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)
        owned_mock.assert_awaited_once_with(session, None)
        move_mock.assert_not_awaited()

    async def test_creates_new_player_linked_to_auth_account_when_no_match(self) -> None:
        """When neither an owned player nor a battletag match exists, the new
        player is created pre-linked to the registering auth account."""
        registration = _reg_stub("BrandNew#444")
        session = _identity_session()

        with (
            patch.object(reg_service, "_find_owned_user", AsyncMock(return_value=None)),
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=None)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()),
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, auth_user_id=99, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 999)
        self.assertEqual(len(session._added), 1)
        self.assertEqual(session._added[0].auth_user_id, 99)

    async def test_live_member_collision_leaves_registration_unanchored(self) -> None:
        """Two live registrations in one tournament resolving to the same player
        (main + smurf row) may not share the member anchor — the partial unique
        index forbids it. The second row keeps its identity provisioning but is
        left unanchored (with a warning) instead of raising IntegrityError."""
        registration = _reg_stub("SmurfRow#555")
        existing_user = SimpleNamespace(id=7)
        session = _identity_session()
        session.scalar = AsyncMock(return_value=True)  # EXISTS guard: collision

        with (
            patch.object(reg_service, "_find_user_by_battle_tag", AsyncMock(return_value=existing_user)),
            patch.object(reg_service, "_ensure_user_battle_tag", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()),
        ):
            resolved = await reg_service.ensure_player_identity(
                session, registration, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        self.assertIsNone(registration.workspace_member_id)
