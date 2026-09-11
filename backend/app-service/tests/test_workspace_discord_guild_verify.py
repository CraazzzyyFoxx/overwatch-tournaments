"""``WorkspaceService.verify_discord_guild`` + the
``rpc.app.workspaces.discord_guild_verify`` RPC handler (workspace
self-service design,
``docs/superpowers/specs/2026-08-26-workspace-self-service-design.md`` §4.1).

Service-layer tests follow the ``SimpleNamespace`` + ``AsyncMock(flush=...)``
style ``test_workspace_custom_domain.py`` uses: ``workspace_repo.update_fields``
is the real ``BaseRepository`` method (setattr loop + ``session.flush()``), so
no DB is needed. The identity-service round trip (``request_rpc``) is patched
at the module-level name it is imported under in ``service.py`` -- the same
seam discipline ``_dns_txt_contains`` gets in the custom-domain tests, rather
than stubbing the whole method.

RPC-layer tests mirror ``test_workspace_discord_rpc.py``'s harness and mock
``workspace_service.verify_discord_guild`` itself -- the deep ownership/
uniqueness/timeout logic is the service tests' job; these only prove the
transport wiring (permission gate, 404, body validation, delegation).
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.schemas.rpc import parse_rpc, rpc_ok  # noqa: E402
from tests.factories import make_workspace as _make_workspace  # noqa: E402

workspace_service = importlib.import_module("src.services.workspace.service")
workspaces = workspace_service.workspaces
_GUILD_ID = "123456789012345678"


def _actor(auth_user_id: int = 42, username: str = "ada") -> SimpleNamespace:
    return SimpleNamespace(id=auth_user_id, username=username)


def _identity_reply(guilds: list[dict]):
    return parse_rpc(rpc_ok({"guilds": guilds}))


class VerifyDiscordGuildTests(IsolatedAsyncioTestCase):
    async def test_verifies_when_actor_administers_the_guild(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()
        reply = _identity_reply([{"guild_id": _GUILD_ID, "name": "G", "owner": True, "can_manage": True}])

        with (
            patch.object(workspace_service, "request_rpc", AsyncMock(return_value=reply)) as req,
            patch.object(workspace_service, "record_audit", AsyncMock()) as audit,
        ):
            result = await workspaces.verify_discord_guild(
                session, workspace, _GUILD_ID, actor=actor, broker=MagicMock()
            )

        self.assertIs(result, workspace)
        self.assertEqual(_GUILD_ID, workspace.discord_guild_id)
        self.assertEqual(42, workspace.discord_guild_verified_by_auth_user_id)
        self.assertIsInstance(workspace.discord_guild_verified_at, datetime)
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        req.assert_awaited_once()
        self.assertEqual({"auth_user_id": 42}, req.await_args.args[1])
        audit.assert_awaited_once()
        self.assertEqual("workspace.discord_guild_verified", audit.await_args.kwargs["action"])
        self.assertEqual(7, audit.await_args.kwargs["entity_id"])

    async def test_can_manage_via_owner_flag_alone_is_sufficient(self) -> None:
        """Discord's ``owner: true`` is proof on its own -- the caller does not
        also need a ``MANAGE_GUILD`` bit set (an owner always implicitly has it,
        but the reply is not required to say so)."""
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()
        reply = _identity_reply([{"guild_id": _GUILD_ID, "name": "G", "owner": True, "can_manage": True}])

        with (
            patch.object(workspace_service, "request_rpc", AsyncMock(return_value=reply)),
            patch.object(workspace_service, "record_audit", AsyncMock()),
        ):
            await workspaces.verify_discord_guild(session, workspace, _GUILD_ID, actor=actor, broker=MagicMock())

        self.assertEqual(_GUILD_ID, workspace.discord_guild_id)

    async def test_rejects_when_actor_does_not_administer_the_guild(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()
        reply = _identity_reply([{"guild_id": "999", "name": "Other Guild", "owner": False, "can_manage": False}])

        with patch.object(workspace_service, "request_rpc", AsyncMock(return_value=reply)):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.verify_discord_guild(session, workspace, _GUILD_ID, actor=actor, broker=MagicMock())

        self.assertEqual(403, ctx.exception.status_code)
        self.assertIsNone(workspace.discord_guild_id)
        session.flush.assert_not_awaited()

    async def test_rejects_when_actor_administers_no_guilds_at_all(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()

        with patch.object(workspace_service, "request_rpc", AsyncMock(return_value=_identity_reply([]))):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.verify_discord_guild(session, workspace, _GUILD_ID, actor=actor, broker=MagicMock())

        self.assertEqual(403, ctx.exception.status_code)
        session.flush.assert_not_awaited()

    async def test_guild_already_claimed_maps_to_409_and_rolls_back(self) -> None:
        session = SimpleNamespace(
            flush=AsyncMock(
                side_effect=IntegrityError(
                    "UPDATE workspace ...",
                    {},
                    Exception('duplicate key value violates unique constraint "uq_workspace_discord_guild_id"'),
                )
            ),
            rollback=AsyncMock(),
        )
        workspace = _make_workspace()
        actor = _actor()
        reply = _identity_reply([{"guild_id": _GUILD_ID, "name": "G", "owner": True, "can_manage": True}])

        with patch.object(workspace_service, "request_rpc", AsyncMock(return_value=reply)):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.verify_discord_guild(session, workspace, _GUILD_ID, actor=actor, broker=MagicMock())

        self.assertEqual(409, ctx.exception.status_code)
        session.rollback.assert_awaited_once()

    async def test_identity_service_unreachable_fails_closed_with_503(self) -> None:
        """Unlike the Boosty subscription resolver (which fails open by
        design), an unreachable identity-service must reject the bind, never
        silently skip the ownership check."""
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()

        with patch.object(workspace_service, "request_rpc", AsyncMock(side_effect=TimeoutError("no reply"))):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.verify_discord_guild(session, workspace, _GUILD_ID, actor=actor, broker=MagicMock())

        self.assertEqual(503, ctx.exception.status_code)
        session.flush.assert_not_awaited()

    async def test_identity_service_error_envelope_fails_closed_with_503(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()
        reply = parse_rpc({"ok": False, "error": {"code": "internal", "message": "boom"}})

        with patch.object(workspace_service, "request_rpc", AsyncMock(return_value=reply)):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.verify_discord_guild(session, workspace, _GUILD_ID, actor=actor, broker=MagicMock())

        self.assertEqual(503, ctx.exception.status_code)
        session.flush.assert_not_awaited()


class ClearDiscordGuildTests(IsolatedAsyncioTestCase):
    async def test_clears_the_claim_and_records_the_before_and_after(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace()
        workspace.discord_guild_id = _GUILD_ID
        workspace.discord_guild_verified_at = datetime.now(UTC)
        workspace.discord_guild_verified_by_auth_user_id = 42
        actor = _actor()

        with patch.object(workspace_service, "record_audit", AsyncMock()) as audit:
            result = await workspaces.clear_discord_guild(session, workspace, actor=actor)

        self.assertIs(result, workspace)
        self.assertIsNone(workspace.discord_guild_id)
        self.assertIsNone(workspace.discord_guild_verified_at)
        self.assertIsNone(workspace.discord_guild_verified_by_auth_user_id)
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        audit.assert_awaited_once()
        self.assertEqual("workspace.discord_guild_cleared", audit.await_args.kwargs["action"])
        self.assertEqual(_GUILD_ID, audit.await_args.kwargs["before"]["discord_guild_id"])
        self.assertEqual(
            {"discord_guild_id": None, "discord_guild_verified_at": None}, audit.await_args.kwargs["after"]
        )

    async def test_an_already_unbound_workspace_is_a_silent_no_op(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace()
        actor = _actor()

        with patch.object(workspace_service, "record_audit", AsyncMock()) as audit:
            await workspaces.clear_discord_guild(session, workspace, actor=actor)

        session.flush.assert_not_awaited()
        session.commit.assert_not_awaited()
        audit.assert_not_awaited()


class ListActorDiscordGuildsTests(IsolatedAsyncioTestCase):
    """The picker that feeds the verify call above: same subject, same timeout,
    same fail-closed 503. An empty list would read as "you administer nothing",
    which is a different -- and misleading -- answer from "we could not ask"."""

    _GUILDS = [
        {"guild_id": _GUILD_ID, "name": "G", "owner": True, "can_manage": True},
        {"guild_id": "999999999999999999", "name": "Other", "owner": False, "can_manage": False},
    ]

    async def test_returns_every_guild_the_actor_sees_unfiltered(self) -> None:
        """Not filtered to ``can_manage``: the picker shows what Discord
        reported and lets ``verify_discord_guild`` be the one gate."""
        with patch.object(
            workspace_service, "request_rpc", AsyncMock(return_value=_identity_reply(self._GUILDS))
        ) as req:
            result = await workspaces.list_actor_discord_guilds(auth_user_id=42, broker=MagicMock())

        self.assertEqual({"guilds": self._GUILDS}, result)
        self.assertEqual({"auth_user_id": 42}, req.await_args.args[1])
        self.assertEqual(workspace_service._DISCORD_GUILDS_SUBJECT, req.await_args.args[2])

    async def test_identity_service_unreachable_fails_closed_with_503(self) -> None:
        with patch.object(workspace_service, "request_rpc", AsyncMock(side_effect=TimeoutError("no reply"))):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.list_actor_discord_guilds(auth_user_id=42, broker=MagicMock())

        self.assertEqual(503, ctx.exception.status_code)

    async def test_identity_service_error_envelope_fails_closed_with_503(self) -> None:
        reply = parse_rpc({"ok": False, "error": {"code": "internal", "message": "boom"}})
        with patch.object(workspace_service, "request_rpc", AsyncMock(return_value=reply)):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspaces.list_actor_discord_guilds(auth_user_id=42, broker=MagicMock())

        self.assertEqual(503, ctx.exception.status_code)


# --- RPC wiring ---------------------------------------------------------

from src.rpc.workspaces import register  # noqa: E402

_IDENTITY = {"user_id": 1, "is_superuser": False, "is_active": True}


def _rpc_reply(body):
    return MagicMock(decode=AsyncMock(return_value=body))


def _register(fake_broker):
    registered: dict[str, object] = {}

    def fake_sub(topic):
        def dec(fn):
            registered[topic] = fn
            return fn

        return dec

    fake_broker.subscriber = fake_sub
    register(fake_broker, MagicMock())
    return registered


_UNSET = object()


class DiscordGuildVerifyRPCTests(IsolatedAsyncioTestCase):
    async def _call(self, data, *, ws=_UNSET, verify_result=None, verify_error=None):
        fake_broker = MagicMock()
        handler = _register(fake_broker)["rpc.app.workspaces.discord_guild_verify"]
        fake_ws = MagicMock(id=1) if ws is _UNSET else ws
        verify = AsyncMock(return_value=verify_result, side_effect=verify_error)
        with (
            patch("src.rpc.workspaces.workspace_service.get_by_id", AsyncMock(return_value=fake_ws)),
            patch("src.rpc.workspaces.workspace_service.verify_discord_guild", verify),
        ):
            result = await handler(data, MagicMock())
        return result, verify

    async def test_requires_workspace_update_permission(self) -> None:
        from shared.core.errors import BaseAPIException

        denied = MagicMock(side_effect=BaseAPIException(status_code=403, detail="Forbidden"))
        with patch("src.rpc.workspaces.ensure_workspace_permission", denied):
            result, verify = await self._call(
                {"workspace_id": 1, "identity": _IDENTITY, "payload": {"guild_id": _GUILD_ID}}
            )

        self.assertNotIn("data", result)
        verify.assert_not_awaited()

    async def test_404s_a_missing_workspace(self) -> None:
        with patch("src.rpc.workspaces.ensure_workspace_permission", MagicMock()):
            result, verify = await self._call(
                {"workspace_id": 1, "identity": _IDENTITY, "payload": {"guild_id": _GUILD_ID}},
                ws=None,
            )

        self.assertNotIn("data", result)
        verify.assert_not_awaited()

    async def test_rejects_a_malformed_guild_id(self) -> None:
        with patch("src.rpc.workspaces.ensure_workspace_permission", MagicMock()):
            result, verify = await self._call(
                {"workspace_id": 1, "identity": _IDENTITY, "payload": {"guild_id": "not-a-snowflake"}}
            )

        self.assertNotIn("data", result)
        verify.assert_not_awaited()

    async def test_delegates_to_the_service_and_returns_workspace_read(self) -> None:
        verified_workspace = SimpleNamespace(
            id=1,
            slug="owt",
            name="OWT",
            description=None,
            icon_url=None,
            is_active=True,
            is_hidden=False,
            timezone="Europe/Moscow",
            branding_enabled=False,
            brand_primary=None,
            brand_secondary=None,
            brand_background=None,
            brand_surface=None,
            brand_accent=None,
            brand_foreground=None,
            brand_muted=None,
            brand_border=None,
            brand_ring=None,
            brand_destructive=None,
            subdomain=None,
            seo_title=None,
            seo_description=None,
            custom_domain=None,
            custom_domain_verified_at=None,
            custom_domain_verification_token=None,
            discord_guild_id=_GUILD_ID,
            discord_guild_verified_at=datetime.now(UTC),
            default_division_grid_version_id=None,
            default_division_grid_version=None,
            default_roster_slots_json=None,
            newcomer_scope="global",
        )
        with patch("src.rpc.workspaces.ensure_workspace_permission", MagicMock()):
            result, verify = await self._call(
                {"workspace_id": 1, "identity": _IDENTITY, "payload": {"guild_id": _GUILD_ID}},
                ws=verified_workspace,
                verify_result=verified_workspace,
            )

        self.assertEqual(_GUILD_ID, result["data"]["discord_guild_id"])
        verify.assert_awaited_once()
        self.assertEqual(_GUILD_ID, verify.await_args.args[2])


class DiscordGuildClearRPCTests(IsolatedAsyncioTestCase):
    async def _call(self, data, *, ws=_UNSET, clear_result=None):
        handler = _register(MagicMock())["rpc.app.workspaces.discord_guild_clear"]
        fake_ws = MagicMock(id=1) if ws is _UNSET else ws
        clear = AsyncMock(return_value=clear_result or fake_ws)
        with (
            patch("src.rpc.workspaces.workspace_service.get_by_id", AsyncMock(return_value=fake_ws)),
            patch("src.rpc.workspaces.workspace_service.clear_discord_guild", clear),
        ):
            result = await handler(data, MagicMock())
        return result, clear

    async def test_requires_workspace_update_permission(self) -> None:
        from shared.core.errors import BaseAPIException

        denied = MagicMock(side_effect=BaseAPIException(status_code=403, detail="Forbidden"))
        with patch("src.rpc.workspaces.ensure_workspace_permission", denied):
            result, clear = await self._call({"workspace_id": 1, "identity": _IDENTITY})

        self.assertNotIn("data", result)
        clear.assert_not_awaited()

    async def test_404s_a_missing_workspace(self) -> None:
        with patch("src.rpc.workspaces.ensure_workspace_permission", MagicMock()):
            result, clear = await self._call({"workspace_id": 1, "identity": _IDENTITY}, ws=None)

        self.assertNotIn("data", result)
        clear.assert_not_awaited()

    async def test_delegates_to_the_service(self) -> None:
        workspace = SimpleNamespace(
            id=1,
            slug="owt",
            name="OWT",
            description=None,
            icon_url=None,
            is_active=True,
            is_hidden=False,
            timezone="Europe/Moscow",
            branding_enabled=False,
            brand_primary=None,
            brand_secondary=None,
            brand_background=None,
            brand_surface=None,
            brand_accent=None,
            brand_foreground=None,
            brand_muted=None,
            brand_border=None,
            brand_ring=None,
            brand_destructive=None,
            subdomain=None,
            seo_title=None,
            seo_description=None,
            custom_domain=None,
            custom_domain_verified_at=None,
            custom_domain_verification_token=None,
            discord_guild_id=None,
            discord_guild_verified_at=None,
            default_division_grid_version_id=None,
            default_division_grid_version=None,
            default_roster_slots_json=None,
            newcomer_scope="global",
        )
        with patch("src.rpc.workspaces.ensure_workspace_permission", MagicMock()):
            result, clear = await self._call(
                {"workspace_id": 1, "identity": _IDENTITY},
                ws=workspace,
                clear_result=workspace,
            )

        self.assertIsNone(result["data"]["discord_guild_id"])
        clear.assert_awaited_once()


class MyDiscordGuildsRPCTests(IsolatedAsyncioTestCase):
    """Actor-scoped, so no workspace id and no workspace permission gate --
    the caller only ever learns about their own Discord account."""

    async def _call(self, data, *, guilds=None, error=None):
        handler = _register(MagicMock())["rpc.app.workspaces.my_discord_guilds"]
        listing = AsyncMock(return_value={"guilds": guilds or []}, side_effect=error)
        with patch("src.rpc.workspaces.workspace_service.list_actor_discord_guilds", listing):
            return await handler(data, MagicMock()), listing

    async def test_returns_the_callers_own_guilds(self) -> None:
        guilds = [{"guild_id": _GUILD_ID, "name": "G", "owner": True, "can_manage": True}]
        result, listing = await self._call({"identity": _IDENTITY}, guilds=guilds)

        self.assertEqual({"guilds": guilds}, result["data"])
        self.assertEqual(1, listing.await_args.kwargs["auth_user_id"])

    async def test_an_inactive_user_gets_nothing(self) -> None:
        result, listing = await self._call({"identity": {**_IDENTITY, "is_active": False}})

        self.assertNotIn("data", result)
        listing.assert_not_awaited()
