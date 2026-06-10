"""Tests for balancer_status, check-in, and computed is_flex logic."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from fastapi import HTTPException  # noqa: E402

from src import models  # noqa: E402
from src.routes.admin import registration as registration_route  # noqa: E402
from src.services.admin import balancer_registration as svc  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registration(
    *,
    status: str = "approved",
    balancer_status: str = "not_in_balancer",
    checked_in: bool = False,
    checked_in_at: datetime | None = None,
    checked_in_by: int | None = None,
    exclude_from_balancer: bool = False,
    roles: list | None = None,
    tournament: SimpleNamespace | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=1,
        tournament_id=10,
        workspace_id=1,
        status=status,
        balancer_status=balancer_status,
        checked_in=checked_in,
        checked_in_at=checked_in_at,
        checked_in_by=checked_in_by,
        exclude_from_balancer=exclude_from_balancer,
        exclude_reason=None,
        roles=roles or [],
        tournament=tournament
        or SimpleNamespace(
            status="check_in",
            check_in_opens_at=now - timedelta(minutes=5),
            check_in_closes_at=now + timedelta(minutes=5),
        ),
        is_flex_computed=False,
        reviewer=None,
        checked_in_by_user=None,
        google_sheet_binding=None,
        deleted_at=None,
    )


def _mock_session_with_registration(registration: SimpleNamespace) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = registration
    session.execute.return_value = result
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# set_balancer_status tests
# ---------------------------------------------------------------------------


class SetBalancerStatusTests(IsolatedAsyncioTestCase):
    async def test_set_balancer_status_ready_for_approved_registration(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            roles=[SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500)],
        )
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.set_balancer_status(session, 1, balancer_status="ready")

        self.assertEqual(result.balancer_status, "ready")
        self.assertFalse(result.exclude_from_balancer)
        session.commit.assert_awaited_once()

    async def test_set_balancer_status_rejects_non_approved_registration(self) -> None:
        reg = _make_registration(status="pending")
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            with self.assertRaises(HTTPException) as ctx:
                await svc.set_balancer_status(session, 1, balancer_status="ready")

        self.assertEqual(ctx.exception.status_code, 409)

    async def test_set_balancer_status_allows_not_in_balancer_for_any_status(self) -> None:
        reg = _make_registration(status="pending", balancer_status="ready")
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.set_balancer_status(session, 1, balancer_status="not_in_balancer")

        self.assertEqual(result.balancer_status, "not_in_balancer")
        self.assertTrue(result.exclude_from_balancer)

    async def test_set_balancer_status_rejects_invalid_status(self) -> None:
        reg = _make_registration(status="approved")
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            with self.assertRaises(HTTPException) as ctx:
                await svc.set_balancer_status(session, 1, balancer_status="invalid")

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_set_balancer_status_allows_workspace_custom_status(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            exclude_from_balancer=True,
        )
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = 123
        session.execute.return_value = result_mock
        session.commit = AsyncMock()

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.set_balancer_status(session, 1, balancer_status="shortcast")

        self.assertEqual(result.balancer_status, "shortcast")
        self.assertTrue(result.exclude_from_balancer)
        session.commit.assert_awaited_once()

    async def test_set_balancer_status_incomplete(self) -> None:
        reg = _make_registration(status="approved")
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.set_balancer_status(session, 1, balancer_status="incomplete")

        self.assertEqual(result.balancer_status, "incomplete")

    async def test_set_balancer_status_ready_rejects_registration_without_active_roles(self) -> None:
        reg = _make_registration(
            status="approved",
            roles=[SimpleNamespace(role="tank", is_primary=True, is_active=False, rank_value=None)],
        )
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            with self.assertRaises(HTTPException) as ctx:
                await svc.set_balancer_status(session, 1, balancer_status="ready")

        self.assertEqual(ctx.exception.status_code, 409)


class ListRegistrationsTests(IsolatedAsyncioTestCase):
    async def test_list_registrations_preloads_auth_user_relationships_for_serialization(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute.return_value = result

        await svc.list_registrations(session, tournament_id=64)

        query = session.execute.await_args.args[0]
        option_paths = {str(option.path) for option in query._with_options}

        for expected_path in (
            "ORM Path[Mapper[BalancerRegistration(registration)] -> BalancerRegistration.auth_user -> Mapper[AuthUser(user)]]",
            "ORM Path[Mapper[BalancerRegistration(registration)] -> BalancerRegistration.reviewer -> Mapper[AuthUser(user)]]",
            "ORM Path[Mapper[BalancerRegistration(registration)] -> BalancerRegistration.deleted_by_user -> Mapper[AuthUser(user)]]",
            "ORM Path[Mapper[BalancerRegistration(registration)] -> BalancerRegistration.checked_in_by_user -> Mapper[AuthUser(user)]]",
        ):
            self.assertIn(expected_path, option_paths)


class UpdateRegistrationProfileBalancerStatusTests(IsolatedAsyncioTestCase):
    async def test_profile_update_demotes_ready_when_active_role_has_no_rank(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="ready",
            roles=[
                SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500),
                SimpleNamespace(role="support", is_primary=False, is_active=False, rank_value=None),
            ],
        )
        session = _mock_session_with_registration(reg)

        updated_roles = [
            {"role": "tank", "is_primary": True, "is_active": True, "rank_value": 2500},
            {"role": "support", "is_primary": False, "is_active": True, "rank_value": None},
        ]

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.update_registration_profile(
                session,
                1,
                display_name=None,
                battle_tag=None,
                smurf_tags_json=None,
                discord_nick=None,
                twitch_nick=None,
                stream_pov=None,
                notes=None,
                admin_notes=None,
                status_value=None,
                balancer_status_value=None,
                roles=updated_roles,
            )

        self.assertEqual(result.balancer_status, "incomplete")

    async def test_profile_update_promotes_to_ready_when_unranked_roles_are_disabled(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="incomplete",
            roles=[
                SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500),
                SimpleNamespace(role="support", is_primary=False, is_active=True, rank_value=None),
            ],
        )
        session = _mock_session_with_registration(reg)

        updated_roles = [
            {"role": "tank", "is_primary": True, "is_active": True, "rank_value": 2500},
            {"role": "support", "is_primary": False, "is_active": False, "rank_value": None},
        ]

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.update_registration_profile(
                session,
                1,
                display_name=None,
                battle_tag=None,
                smurf_tags_json=None,
                discord_nick=None,
                twitch_nick=None,
                stream_pov=None,
                notes=None,
                admin_notes=None,
                status_value=None,
                balancer_status_value=None,
                roles=updated_roles,
            )

        self.assertEqual(result.balancer_status, "ready")

    async def test_profile_update_custom_balancer_status_includes_registration(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            exclude_from_balancer=True,
        )
        session = _mock_session_with_registration(reg)

        with (
            patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)),
            patch.object(svc, "validate_registration_status_value", AsyncMock()),
        ):
            result = await svc.update_registration_profile(
                session,
                1,
                display_name=None,
                battle_tag=None,
                smurf_tags_json=None,
                discord_nick=None,
                twitch_nick=None,
                stream_pov=None,
                notes=None,
                admin_notes=None,
                status_value=None,
                balancer_status_value="shortcast",
                roles=None,
            )

        self.assertEqual(result.balancer_status, "shortcast")
        self.assertTrue(result.exclude_from_balancer)


# ---------------------------------------------------------------------------
# check_in / uncheck_in tests
# ---------------------------------------------------------------------------


class CheckInTests(IsolatedAsyncioTestCase):
    async def test_check_in_sets_fields(self) -> None:
        reg = _make_registration(checked_in=False)
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.check_in_registration(session, 1, checked_in_by=42)

        self.assertTrue(result.checked_in)
        self.assertIsNotNone(result.checked_in_at)
        self.assertEqual(result.checked_in_by, 42)
        session.commit.assert_awaited_once()

    async def test_check_in_rejects_inactive_window(self) -> None:
        now = datetime.now(UTC)
        reg = _make_registration(
            checked_in=False,
            tournament=SimpleNamespace(
                status="check_in",
                check_in_opens_at=now + timedelta(minutes=5),
                check_in_closes_at=now + timedelta(minutes=10),
            ),
        )
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            with self.assertRaises(HTTPException) as exc_info:
                await svc.check_in_registration(session, 1, checked_in_by=42)

        self.assertEqual(409, exc_info.exception.status_code)
        self.assertEqual("Check-in is not active for this tournament", exc_info.exception.detail)
        session.commit.assert_not_awaited()

    async def test_uncheck_in_resets_fields(self) -> None:
        reg = _make_registration(
            checked_in=True,
            checked_in_at=datetime.now(UTC),
            checked_in_by=42,
        )
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.uncheck_in_registration(session, 1)

        self.assertFalse(result.checked_in)
        self.assertIsNone(result.checked_in_at)
        self.assertIsNone(result.checked_in_by)
        session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Computed is_flex tests
# ---------------------------------------------------------------------------


class ComputedIsFlexTests(IsolatedAsyncioTestCase):
    def test_is_flex_computed_true_when_all_roles_are_primary(self) -> None:
        reg = models.BalancerRegistration()
        role_primary = models.BalancerRegistrationRole(role="tank", is_primary=True, priority=0)
        second_primary = models.BalancerRegistrationRole(role="support", is_primary=True, priority=1)
        reg.roles = [role_primary, second_primary]

        self.assertTrue(reg.is_flex_computed)

    def test_is_flex_computed_false_when_any_role_is_secondary(self) -> None:
        reg = models.BalancerRegistration()
        role_primary = models.BalancerRegistrationRole(role="tank", is_primary=True, priority=0)
        role_secondary = models.BalancerRegistrationRole(role="support", is_primary=False, priority=1)
        reg.roles = [role_primary, role_secondary]

        self.assertFalse(reg.is_flex_computed)

    def test_is_flex_computed_false_when_no_roles(self) -> None:
        reg = models.BalancerRegistration()
        reg.roles = []

        self.assertFalse(reg.is_flex_computed)

    def test_serializer_skips_unloaded_auth_user_relationships(self) -> None:
        reg = models.BalancerRegistration(
            id=1,
            tournament_id=64,
            workspace_id=1,
            auth_user_id=7,
            reviewed_by=7,
            checked_in_by=7,
            status="approved",
            balancer_status="not_in_balancer",
            stream_pov=False,
            exclude_from_balancer=False,
            checked_in=True,
        )
        reg.roles = []

        payload = registration_route._serialize_registration(reg)

        self.assertIsNone(payload.reviewed_by_username)
        self.assertIsNone(payload.checked_in_by_username)
        self.assertEqual(payload.roles, [])


# ---------------------------------------------------------------------------
# bulk_add_to_balancer tests
# ---------------------------------------------------------------------------


class BulkAddToBalancerTests(IsolatedAsyncioTestCase):
    async def test_bulk_add_to_balancer_updates_approved_registrations(self) -> None:
        reg1 = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            roles=[SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500)],
        )
        reg2 = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            roles=[SimpleNamespace(role="support", is_primary=True, is_active=True, rank_value=2400)],
        )
        reg2.id = 2

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [reg1, reg2]
        session.execute.return_value = result_mock
        session.commit = AsyncMock()

        updated, skipped = await svc.bulk_add_to_balancer(session, 10, [1, 2], balancer_status="ready")

        self.assertEqual(updated, 2)
        self.assertEqual(skipped, 0)
        self.assertEqual(reg1.balancer_status, "ready")
        self.assertEqual(reg2.balancer_status, "ready")
        self.assertFalse(reg1.exclude_from_balancer)
        self.assertFalse(reg2.exclude_from_balancer)
        session.commit.assert_awaited_once()

    async def test_bulk_add_to_balancer_skips_non_approved(self) -> None:
        reg1 = _make_registration(
            status="approved",
            roles=[SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500)],
        )
        # Only 1 of 3 is returned (the other 2 are not approved)

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [reg1]
        session.execute.return_value = result_mock
        session.commit = AsyncMock()

        updated, skipped = await svc.bulk_add_to_balancer(session, 10, [1, 2, 3], balancer_status="ready")

        self.assertEqual(updated, 1)
        self.assertEqual(skipped, 2)

    async def test_bulk_add_to_balancer_marks_roleless_registrations_incomplete(self) -> None:
        reg = _make_registration(status="approved", balancer_status="not_in_balancer", roles=[])

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [reg]
        session.execute.return_value = result_mock
        session.commit = AsyncMock()

        updated, skipped = await svc.bulk_add_to_balancer(session, 10, [1], balancer_status="ready")

        self.assertEqual(updated, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(reg.balancer_status, "incomplete")
        self.assertFalse(reg.exclude_from_balancer)

    async def test_bulk_add_to_balancer_allows_workspace_custom_status(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            exclude_from_balancer=True,
            roles=[SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500)],
        )

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [reg]
        session.execute.return_value = result_mock
        session.commit = AsyncMock()

        with (
            patch.object(svc, "ensure_tournament_exists", AsyncMock(return_value=SimpleNamespace(workspace_id=1))),
            patch.object(svc, "validate_registration_status_value", AsyncMock()),
        ):
            updated, skipped = await svc.bulk_add_to_balancer(session, 10, [1], balancer_status="shortcast")

        self.assertEqual(updated, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(reg.balancer_status, "shortcast")
        self.assertFalse(reg.exclude_from_balancer)


class RegistrationExclusionTests(IsolatedAsyncioTestCase):
    async def test_excluding_registration_forces_not_in_balancer(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="ready",
            roles=[SimpleNamespace(role="tank", is_primary=True, is_active=True, rank_value=2500)],
        )
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.set_registration_exclusion(
                session,
                1,
                exclude_from_balancer=True,
                exclude_reason="manual_exclusion",
            )

        self.assertTrue(result.exclude_from_balancer)
        self.assertEqual(result.exclude_reason, "manual_exclusion")
        self.assertEqual(result.balancer_status, "not_in_balancer")

    async def test_reincluding_roleless_registration_marks_it_incomplete(self) -> None:
        reg = _make_registration(
            status="approved",
            balancer_status="not_in_balancer",
            exclude_from_balancer=True,
            roles=[],
        )
        session = _mock_session_with_registration(reg)

        with patch.object(svc, "get_registration_by_id", AsyncMock(return_value=reg)):
            result = await svc.set_registration_exclusion(
                session,
                1,
                exclude_from_balancer=False,
                exclude_reason=None,
            )

        self.assertFalse(result.exclude_from_balancer)
        self.assertIsNone(result.exclude_reason)
        self.assertEqual(result.balancer_status, "incomplete")
