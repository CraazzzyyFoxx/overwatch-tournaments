"""Tests for player-identity resolution during Google Sheets registration sync.

The bug: ``sync_google_sheet_feed`` created/updated ``Registration`` rows
without resolving the player identity (unlike the web form's
``create_registration``, which calls ``ensure_player_identity``). Without an
identity anchor the OW-rank lookup finds nothing and the balancer rank-delta UI
stays empty. Since dbarch02 dropped ``registration.user_id``, the anchor is
``workspace_member_id`` (member.player_id IS the domain player id).

These tests cover identity linking, creation, member anchoring and idempotence.
Real PostgreSQL checks keep invalid answers atomic; fresh optional-identity
writers are covered in ``test_registration_identity_db.py``.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

# Patch targets must be the module that OWNS ``sync_google_sheet_feed`` (sheet_sync),
# not the ``admin`` facade (which no longer exists). Since the service became a
# class, its collaborators live in three different places: methods on the
# ``sheet_sync_service`` singleton, the injected ``_common_service`` behind
# ``sheet_sync_service.common``, and plain module globals of sheet_sync.
# ``ensure_player_identity`` is a method on the ``registration_service``
# singleton that sheet_sync imports.
reg_admin = importlib.import_module("src.services.registration.sheet_sync")
reg_service = importlib.import_module("src.services.registration.service")

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.core.social import SocialProvider, normalize_social_handle  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    RegistrationForm,
    RegistrationFormVersion,
    RegistrationGoogleSheetFeed,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from tests._lol_grid import seed_lol_grid  # noqa: E402

_WORKSPACE_ID = 1
_MEMBER_ID = 501


def _identity_row(provider: str, handle: str, position: int = 0) -> models.RegistrationIdentity:
    return models.RegistrationIdentity(
        provider=provider,
        position=position,
        handle=handle,
        handle_normalized=normalize_social_handle(provider, handle),
    )


def _reg_stub(
    handle: str | None,
    *,
    workspace_member_id: int | None = None,
    extra_identities: list[models.RegistrationIdentity] | None = None,
) -> SimpleNamespace:
    """A registration stub mirroring the ORM row: no user_id column (dropped
    by dbarch02); identity is the ``workspace_member_id`` anchor, and the
    handles live in ``identities`` rows, not on the row itself."""
    identities = [] if handle is None else [_identity_row(SocialProvider.BATTLENET, handle)]
    identities += extra_identities or []
    return SimpleNamespace(
        id=321,
        tournament_id=77,
        identities=identities,
        workspace_member_id=workspace_member_id,
        deleted_at=None,
    )


def _identity_session(
    *,
    added: list[object] | None = None,
    get: AsyncMock | None = None,
    collides: bool = False,
    first: object | None = None,
) -> SimpleNamespace:
    """Session stub for ensure_player_identity.

    ``execute`` now serves two repository reads that used to be session calls:
    the live-collision EXISTS guard in _anchor_registration_member
    (``registration_repo.exists`` -> ``scalar_one_or_none() is True``, so
    ``collides`` drives it) and the already-linked player lookup
    (``user_repo.get`` -> ``unique().scalars().first()``, driven by ``first``).
    ``session.get`` is still used directly for the WorkspaceMember anchor.
    """
    added_list = [] if added is None else added

    async def _flush() -> None:
        for obj in added_list:
            if isinstance(obj, reg_service.models.User) and getattr(obj, "id", None) is None:
                obj.id = 999

    result = Mock()
    result.unique.return_value = result
    result.scalars.return_value.first.return_value = first
    result.scalar_one_or_none.return_value = True if collides else None
    return SimpleNamespace(
        get=get or AsyncMock(return_value=None),
        add=lambda obj: added_list.append(obj),
        flush=AsyncMock(side_effect=_flush),
        execute=AsyncMock(return_value=result),
        _added=added_list,
    )


def _member_anchor_patch() -> AsyncMock:
    return AsyncMock(return_value=SimpleNamespace(id=_MEMBER_ID, player_id=None))


class EnsurePlayerIdentitySemanticsTests(IsolatedAsyncioTestCase):
    async def test_links_existing_account_by_game_handle(self) -> None:
        registration = _reg_stub("Existing#111")
        existing_user = SimpleNamespace(id=7)
        session = _identity_session()

        with (
            patch.object(
                reg_service.registration_service,
                "_find_user_by_handles",
                AsyncMock(return_value=(existing_user, "Existing#111")),
            ),
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, workspace_id=_WORKSPACE_ID
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
            self.assertIs(model, reg_service.models.WorkspaceMember)
            self.assertEqual(pk, 10)
            return member

        # The already-linked player is now read through ``user_repo.get``, i.e.
        # ``session.execute(...).unique().scalars().first()``.
        session = _identity_session(get=AsyncMock(side_effect=_get), first=linked_user)
        find_mock = AsyncMock()

        with (
            patch.object(reg_service.registration_service, "_find_user_by_handles", find_mock),
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, workspace_id=_WORKSPACE_ID
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
            patch.object(reg_service.registration_service, "_find_user_by_handles", AsyncMock(return_value=None)),
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, workspace_id=_WORKSPACE_ID
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
            patch.object(reg_service.registration_service, "_find_user_by_handles", AsyncMock(return_value=None)),
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()),
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 999)

    async def test_reuses_account_owned_player_over_game_handle_dedup(self) -> None:
        """Case (a): the auth account already owns a player and the game handle has
        no distinct shadow owner — the account-owned player wins, no collapse."""
        registration = _reg_stub("AccountOwner#111")
        owned_user = SimpleNamespace(id=7)
        session = _identity_session()

        with (
            patch.object(reg_service.registration_service, "_find_owned_user", AsyncMock(return_value=owned_user)),
            patch.object(
                reg_service.registration_service,
                "_find_user_by_handles",
                AsyncMock(return_value=None),  # nobody ELSE holds the handle
            ),
            patch.object(reg_service.registration_service, "_move_game_identity", AsyncMock()) as move_mock,
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, auth_user_id=42, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=7)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)
        move_mock.assert_not_awaited()

    async def test_colliding_shadow_game_handle_triggers_identity_collapse(self) -> None:
        """Case (b): the auth account owns a player, but a DIFFERENT shadow
        player already holds the game handle — collapse the shadow's identity for
        that provider onto the account-owned player instead of splitting it."""
        registration = _reg_stub("Shadow#222")
        owned_user = SimpleNamespace(id=7)
        shadow_user = SimpleNamespace(id=13)
        session = _identity_session()

        with (
            patch.object(reg_service.registration_service, "_find_owned_user", AsyncMock(return_value=owned_user)),
            patch.object(
                reg_service.registration_service,
                "_find_user_by_handles",
                AsyncMock(return_value=(shadow_user, "Shadow#222")),
            ),
            patch.object(reg_service.registration_service, "_move_game_identity", AsyncMock()) as move_mock,
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, auth_user_id=42, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=7)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)
        move_mock.assert_awaited_once_with(
            session, provider=SocialProvider.BATTLENET, shadow=shadow_user, target=owned_user, handle="Shadow#222"
        )

    async def test_shadow_only_no_account_unchanged(self) -> None:
        """Case (c): no auth account owns a player (anonymous/sheet import) —
        behaviour is exactly the pre-existing game-handle dedup, plus the member
        anchor for the resolved shadow player."""
        registration = _reg_stub("ShadowOnly#333")
        shadow_user = SimpleNamespace(id=21)
        session = _identity_session()

        with (
            patch.object(
                reg_service.registration_service, "_find_owned_user", AsyncMock(return_value=None)
            ) as owned_mock,
            patch.object(
                reg_service.registration_service,
                "_find_user_by_handles",
                AsyncMock(return_value=(shadow_user, "ShadowOnly#333")),
            ),
            patch.object(reg_service.registration_service, "_move_game_identity", AsyncMock()) as move_mock,
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, auth_user_id=None, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 21)
        member_mock.assert_awaited_once_with(session, workspace_id=_WORKSPACE_ID, player_id=21)
        self.assertEqual(registration.workspace_member_id, _MEMBER_ID)
        owned_mock.assert_awaited_once_with(session, None)
        move_mock.assert_not_awaited()

    async def test_creates_new_player_linked_to_auth_account_when_no_match(self) -> None:
        """When neither an owned player nor a game-handle match exists, the new
        player is created pre-linked to the registering auth account."""
        registration = _reg_stub("BrandNew#444")
        session = _identity_session()

        with (
            patch.object(reg_service.registration_service, "_find_owned_user", AsyncMock(return_value=None)),
            patch.object(reg_service.registration_service, "_find_user_by_handles", AsyncMock(return_value=None)),
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()),
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, auth_user_id=99, workspace_id=_WORKSPACE_ID
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
        session = _identity_session(collides=True)  # EXISTS guard: collision

        with (
            patch.object(
                reg_service.registration_service,
                "_find_user_by_handles",
                AsyncMock(return_value=(existing_user, "SmurfRow#555")),
            ),
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()),
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()),
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, workspace_id=_WORKSPACE_ID
            )

        self.assertEqual(resolved, 7)
        self.assertIsNone(registration.workspace_member_id)

    async def test_a_registration_with_no_game_handle_resolves_to_no_player(self) -> None:
        """A discord handle says nothing about WHICH player this is: with no game
        identity and no auth account owning one, nothing is found and nothing is
        created -- the row stays unanchored."""
        registration = _reg_stub(None, extra_identities=[_identity_row(SocialProvider.DISCORD, "someone")])
        session = _identity_session()

        with (
            patch.object(reg_service.registration_service, "_ensure_social_accounts", AsyncMock()) as ensure_mock,
            patch.object(reg_service, "get_or_create_workspace_member", _member_anchor_patch()) as member_mock,
        ):
            resolved = await reg_service.registration_service.ensure_player_identity(
                session, registration, provider=SocialProvider.BATTLENET, workspace_id=_WORKSPACE_ID
            )

        self.assertIsNone(resolved)
        self.assertEqual(session._added, [])
        ensure_mock.assert_not_awaited()
        member_mock.assert_not_awaited()
        self.assertIsNone(registration.workspace_member_id)


# ── one bad row must not be written, and must not stop the sheet ────────────
#
# Against a real database on purpose. The claim is about what reaches the
# TABLES -- no registration, no identity row, no half-written columns -- which
# a fake session cannot witness: it would only show which methods were called.

_ATOMIC_SCHEMA = FormSchema(
    sections=[
        FormSection(
            key="accounts",
            fields=[
                FormField(key="identity_battlenet", kind="builtin", required=True),
                FormField(key="identity_discord", kind="builtin"),
                FormField(key="public_notes", kind="builtin"),
            ],
        )
    ]
)

_ATOMIC_HEADERS = ["BattleTag", "Discord", "Note"]
_ATOMIC_MAPPING = {
    "targets": {
        "source_record_key": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
        "identity_battlenet": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag_list"},
        "identity_discord": {"mode": "columns", "columns": ["Discord"], "parser": "string"},
        "public_notes": {"mode": "columns", "columns": ["Note"], "parser": "join_lines"},
    }
}


async def _seed_feed(
    session: Any,
    *,
    discipline: str = "overwatch",
    schema: FormSchema = _ATOMIC_SCHEMA,
    mapping: dict[str, Any] | None = _ATOMIC_MAPPING,
) -> dict[str, int]:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(
        slug=f"sheetatomic-{suffix}", name=f"Sheet atomic {suffix}", disciplines_enabled=["overwatch", "lol"]
    )
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Sheet atomic {suffix}",
        slug=f"sheetatomic-{suffix}",
        discipline=discipline,
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    if discipline == "lol":
        tournament.division_grid_version_id = await seed_lol_grid(session, workspace_id=workspace.id, suffix=suffix)
        await session.flush()
    form = RegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id)
    session.add(form)
    await session.flush()
    form.current_version = RegistrationFormVersion(
        form_id=form.id, number=1, schema_json=schema.model_dump(mode="json")
    )
    await session.flush()
    session.add(
        RegistrationGoogleSheetFeed(
            tournament_id=tournament.id,
            source_url="http://sheet.example/atomic",
            sheet_id="sheet-atomic",
            mapping_config_json=mapping,
        )
    )
    await session.commit()
    return {"workspace_id": workspace.id, "tournament_id": tournament.id}


def test_a_row_whose_answers_do_not_validate_is_skipped_whole(db_session, monkeypatch) -> None:
    """The bad row writes NOTHING and the good row still lands.

    Ordering matters: the failing row is first, so a sync that created the
    registration before validating its answers -- or that let the first bad row
    abort the pass -- fails here on the row count.
    """

    async def _run() -> None:
        seeded = await _seed_feed(db_session)

        async def _fetch(*_args, **_kwargs):
            return [
                _ATOMIC_HEADERS,
                # ``identity_discord`` has a DEFAULT_PATTERNS grammar; spaces and
                # bangs are not in it.
                ["Bad#1111", "NOT A HANDLE!!", "bad note"],
                ["Good#2222", "gooddiscord", "good note"],
            ]

        monkeypatch.setattr(reg_admin, "fetch_google_sheet_rows", _fetch)

        result = await reg_admin.sheet_sync_service.sync_google_sheet_feed(db_session, seeded["tournament_id"])

        assert result.created == 1
        assert result.skipped == 1
        assert [(error["target"], error["code"], error["row_index"]) for error in result.errors] == [
            ("identity_discord", "invalid_format", 0)
        ]

        rows = (
            (
                await db_session.execute(
                    sa.select(models.Registration)
                    .where(models.Registration.tournament_id == seeded["tournament_id"])
                    .options(selectinload(models.Registration.identities))
                )
            )
            .unique()
            .scalars()
            .all()
        )
        # The bad row left no registration at all -- not an empty one, not one
        # with only the columns validated before the failure.
        assert [row.primary_handle(SocialProvider.BATTLENET) for row in rows] == ["Good#2222"]
        assert rows[0].public_notes == "good note"
        assert [(i.provider, i.handle) for i in rows[0].identities] == [
            ("battlenet", "Good#2222"),
            ("discord", "gooddiscord"),
        ]

        await db_session.execute(sa.delete(Workspace).where(Workspace.id == seeded["workspace_id"]))
        await db_session.commit()

    asyncio.run(_run())


_LOL_SCHEMA = FormSchema(
    sections=[
        FormSection(
            key="accounts",
            fields=[
                FormField(key="identity_riot", kind="builtin", required=True),
                FormField(key="identity_battlenet", kind="builtin"),
            ],
        )
    ]
)
_LOL_HEADERS = ["Riot ID", "BattleTag"]
_LOL_MAPPING = {
    "targets": {
        "identity_riot": {"mode": "columns", "columns": ["Riot ID"], "parser": "battle_tag_list"},
        "identity_battlenet": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag_list"},
    }
}


def test_a_lol_sheet_row_is_keyed_named_and_anchored_by_the_riot_id(db_session, monkeypatch) -> None:
    """A League tournament's sheet row carrying BOTH handles: the Riot ID is the row's
    identity (key, registration match, player name, serialized handle); the BattleTag is
    an extra profile handle, never the identity. A re-sync of the unchanged row creates nothing and skips it."""

    async def _run() -> None:
        seeded = await _seed_feed(db_session, discipline="lol", schema=_LOL_SCHEMA, mapping=_LOL_MAPPING)

        async def _fetch(*_args, **_kwargs):
            return [_LOL_HEADERS, ["Faker#KR1", "Stray#9999"]]

        monkeypatch.setattr(reg_admin, "fetch_google_sheet_rows", _fetch)

        first = await reg_admin.sheet_sync_service.sync_google_sheet_feed(db_session, seeded["tournament_id"])
        again = await reg_admin.sheet_sync_service.sync_google_sheet_feed(db_session, seeded["tournament_id"])

        assert (first.created, first.updated) == (1, 0)
        assert (again.created, again.updated) == (0, 0)

        registration = (
            (
                await db_session.execute(
                    sa.select(models.Registration)
                    .where(models.Registration.tournament_id == seeded["tournament_id"])
                    .options(
                        selectinload(models.Registration.identities),
                        selectinload(models.Registration.workspace_member).selectinload(models.WorkspaceMember.player),
                        selectinload(models.Registration.google_sheet_binding),
                    )
                )
            )
            .unique()
            .scalar_one()
        )
        assert registration.primary_game_identity(provider=SocialProvider.RIOT).handle == "Faker#KR1"
        assert registration.display_name == "Faker#KR1"
        assert registration.google_sheet_binding.source_record_key == normalize_social_handle(
            SocialProvider.RIOT, "Faker#KR1"
        )
        # The anchored player is named after the Riot ID and carries both accounts.
        player = registration.workspace_member.player
        assert player.name == "Faker#KR1"
        accounts = {
            (account.provider, account.username_normalized)
            for account in (
                await db_session.execute(
                    sa.select(models.SocialAccount).where(models.SocialAccount.user_id == player.id)
                )
            )
            .scalars()
            .all()
        }
        assert accounts == {
            (SocialProvider.RIOT, normalize_social_handle(SocialProvider.RIOT, "Faker#KR1")),
            (SocialProvider.BATTLENET, normalize_social_handle(SocialProvider.BATTLENET, "Stray#9999")),
        }

        await db_session.execute(sa.delete(Workspace).where(Workspace.id == seeded["workspace_id"]))
        await db_session.commit()

    asyncio.run(_run())


def test_a_lol_row_with_only_a_battletag_is_not_identified_by_it(db_session, monkeypatch) -> None:
    """The Riot ID is required by the League form, and a BattleTag alone must not become
    the row's key or create a player: the row is skipped, nothing is written."""

    async def _run() -> None:
        seeded = await _seed_feed(db_session, discipline="lol", schema=_LOL_SCHEMA, mapping=_LOL_MAPPING)

        async def _fetch(*_args, **_kwargs):
            return [_LOL_HEADERS, ["", "OnlyBattle#1234"]]

        monkeypatch.setattr(reg_admin, "fetch_google_sheet_rows", _fetch)

        result = await reg_admin.sheet_sync_service.sync_google_sheet_feed(db_session, seeded["tournament_id"])

        assert result.created == 0
        count = await db_session.scalar(
            sa.select(sa.func.count())
            .select_from(models.Registration)
            .where(models.Registration.tournament_id == seeded["tournament_id"])
        )
        assert count == 0
        assert (
            await db_session.scalar(
                sa.select(sa.func.count())
                .select_from(models.SocialAccount)
                .where(
                    models.SocialAccount.username_normalized == normalize_social_handle("battlenet", "OnlyBattle#1234")
                )
            )
            == 0
        )

        await db_session.execute(sa.delete(Workspace).where(Workspace.id == seeded["workspace_id"]))
        await db_session.commit()

    asyncio.run(_run())


def test_the_suggested_lol_mapping_keeps_riot_ids_that_differ_only_by_a_space_apart(db_session, monkeypatch) -> None:
    """No saved mapping: the sync uses the suggested one. ``Foo Bar#123`` and ``FooBar#123`` are two
    people, so the automatically inferred keys must keep the internal space (Riot normalization),
    not collapse into one dictionary slot; a shared optional BattleTag column must not become the
    key either (the generic alias loop would suggest it). A re-sync of the unchanged sheet creates nothing and
    skips both rows."""

    async def _run() -> None:
        seeded = await _seed_feed(db_session, discipline="lol", schema=_LOL_SCHEMA, mapping=None)

        async def _fetch(*_args, **_kwargs):
            return [_LOL_HEADERS, ["Foo Bar#123", "Shared#1111"], ["FooBar#123", "Shared#1111"]]

        monkeypatch.setattr(reg_admin, "fetch_google_sheet_rows", _fetch)

        first = await reg_admin.sheet_sync_service.sync_google_sheet_feed(db_session, seeded["tournament_id"])
        again = await reg_admin.sheet_sync_service.sync_google_sheet_feed(db_session, seeded["tournament_id"])

        assert (first.created, first.updated) == (2, 0)
        assert (again.created, again.updated) == (0, 0)
        keys = (
            await db_session.scalars(
                sa.select(models.RegistrationGoogleSheetBinding.source_record_key)
                .join(
                    models.RegistrationGoogleSheetFeed,
                    models.RegistrationGoogleSheetFeed.id == models.RegistrationGoogleSheetBinding.feed_id,
                )
                .where(models.RegistrationGoogleSheetFeed.tournament_id == seeded["tournament_id"])
            )
        ).all()
        assert sorted(keys) == ["foo bar#123", "foobar#123"]

        await db_session.execute(sa.delete(Workspace).where(Workspace.id == seeded["workspace_id"]))
        await db_session.commit()

    asyncio.run(_run())
