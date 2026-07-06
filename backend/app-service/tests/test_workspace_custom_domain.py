"""Unit tests for the custom-domain set/verify/clear service helpers (Task 5).

No DB required: ``_workspace_repo.update_fields`` is the real
``BaseRepository.update_fields`` (setattr loop + ``session.flush()``), driven
against a ``SimpleNamespace`` workspace + an ``AsyncMock`` session — the same
style ``test_workspace_service.py`` uses for ``update``/``add_member_with_roles``.
The DNS resolver is monkeypatched at ``dns.asyncresolver.resolve`` (the exact
seam ``_dns_txt_contains`` calls), never hitting the network.
"""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import dns.exception
import dns.rdataclass
import dns.rdatatype
import dns.resolver
from dns.rdtypes.ANY.TXT import TXT

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

workspace_service = importlib.import_module("src.services.workspace.service")


def _txt_answer(*values: str) -> list[TXT]:
    """Build real ``dns.rdtypes.ANY.TXT.TXT`` rdata, matching what
    ``dns.asyncresolver.resolve(..., "TXT")`` yields in production — closer to
    the truth than a hand-rolled stand-in for ``rdata.strings``."""
    return [TXT(dns.rdataclass.IN, dns.rdatatype.TXT, [v.encode()]) for v in values]


class DnsTxtContainsTests(IsolatedAsyncioTestCase):
    """``_dns_txt_contains``: match -> True, no-match/any DNS error -> False."""

    async def test_matching_record_returns_true(self) -> None:
        with patch.object(
            workspace_service.dns.asyncresolver, "resolve", AsyncMock(return_value=_txt_answer("owt-verify-abc123"))
        ) as resolve:
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertTrue(result)
        resolve.assert_awaited_once_with("_owt-verify.example.com", "TXT")

    async def test_matching_record_among_multiple_returns_true(self) -> None:
        with patch.object(
            workspace_service.dns.asyncresolver,
            "resolve",
            AsyncMock(return_value=_txt_answer("some-other-value", "owt-verify-abc123")),
        ):
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertTrue(result)

    async def test_non_matching_record_returns_false(self) -> None:
        with patch.object(
            workspace_service.dns.asyncresolver, "resolve", AsyncMock(return_value=_txt_answer("owt-verify-wrong"))
        ):
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertFalse(result)

    async def test_empty_answer_returns_false(self) -> None:
        with patch.object(workspace_service.dns.asyncresolver, "resolve", AsyncMock(return_value=[])):
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertFalse(result)

    async def test_nxdomain_returns_false(self) -> None:
        with patch.object(
            workspace_service.dns.asyncresolver,
            "resolve",
            AsyncMock(side_effect=dns.resolver.NXDOMAIN()),
        ):
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertFalse(result)

    async def test_generic_dns_exception_returns_false(self) -> None:
        with patch.object(
            workspace_service.dns.asyncresolver,
            "resolve",
            AsyncMock(side_effect=dns.exception.DNSException("boom")),
        ):
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertFalse(result)

    async def test_unexpected_exception_also_returns_false(self) -> None:
        # Fail-closed even on a non-DNS error (e.g. resolver misconfiguration) —
        # verification must never 500, only report "not verified yet".
        with patch.object(
            workspace_service.dns.asyncresolver, "resolve", AsyncMock(side_effect=RuntimeError("resolver down"))
        ):
            result = await workspace_service._dns_txt_contains("_owt-verify.example.com", "owt-verify-abc123")

        self.assertFalse(result)


def _make_workspace(**overrides) -> SimpleNamespace:
    base = {
        "id": 7,
        "custom_domain": None,
        "custom_domain_verification_token": None,
        "custom_domain_verified_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class SetCustomDomainTests(IsolatedAsyncioTestCase):
    async def test_normalizes_domain_generates_token_and_resets_verification(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(
            custom_domain="stale.example.com",
            custom_domain_verification_token="owt-verify-stale",
            custom_domain_verified_at=datetime.now(UTC),
        )

        result = await workspace_service.set_custom_domain(session, workspace, "Tourney.Customer.com")

        self.assertIs(result, workspace)
        self.assertEqual("tourney.customer.com", workspace.custom_domain)  # normalized (lowercased)
        self.assertTrue(workspace.custom_domain_verification_token.startswith("owt-verify-"))
        self.assertNotEqual("owt-verify-stale", workspace.custom_domain_verification_token)  # freshly generated
        self.assertIsNone(workspace.custom_domain_verified_at)  # re-pointing resets verification
        session.flush.assert_awaited_once()

    async def test_generates_a_distinct_token_each_call(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()

        await workspace_service.set_custom_domain(session, workspace, "example.com")
        first_token = workspace.custom_domain_verification_token
        await workspace_service.set_custom_domain(session, workspace, "example.com")
        second_token = workspace.custom_domain_verification_token

        self.assertNotEqual(first_token, second_token)

    async def test_rejects_invalid_domain_without_touching_the_workspace(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()

        with self.assertRaises(ValueError):
            await workspace_service.set_custom_domain(session, workspace, "not a domain")

        self.assertIsNone(workspace.custom_domain)
        session.flush.assert_not_awaited()

    async def test_rejects_domain_under_the_platform_zone(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()

        with self.assertRaises(ValueError):
            await workspace_service.set_custom_domain(session, workspace, "team-a.owt.craazzzyyfoxx.me")

        session.flush.assert_not_awaited()


class ClearCustomDomainTests(IsolatedAsyncioTestCase):
    async def test_clears_all_three_fields(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
            custom_domain_verified_at=datetime.now(UTC),
        )

        result = await workspace_service.clear_custom_domain(session, workspace)

        self.assertIs(result, workspace)
        self.assertIsNone(workspace.custom_domain)
        self.assertIsNone(workspace.custom_domain_verification_token)
        self.assertIsNone(workspace.custom_domain_verified_at)
        session.flush.assert_awaited_once()


class VerifyCustomDomainTests(IsolatedAsyncioTestCase):
    async def test_raises_400_when_no_domain_is_set(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace()

        with self.assertRaises(workspace_service.HTTPException) as ctx:
            await workspace_service.verify_custom_domain(session, workspace)

        self.assertEqual(400, ctx.exception.status_code)
        session.flush.assert_not_awaited()

    async def test_raises_400_when_domain_set_but_token_missing(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(custom_domain="tourney.customer.com", custom_domain_verification_token=None)

        with self.assertRaises(workspace_service.HTTPException) as ctx:
            await workspace_service.verify_custom_domain(session, workspace)

        self.assertEqual(400, ctx.exception.status_code)

    async def test_dns_match_stamps_verified_at(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )

        with patch.object(
            workspace_service, "_dns_txt_contains", AsyncMock(return_value=True)
        ) as dns_check:
            result = await workspace_service.verify_custom_domain(session, workspace)

        self.assertIs(result, workspace)
        dns_check.assert_awaited_once_with("_owt-verify.tourney.customer.com", "owt-verify-abc123")
        self.assertIsInstance(workspace.custom_domain_verified_at, datetime)
        session.flush.assert_awaited_once()

    async def test_dns_no_match_raises_400_and_does_not_stamp(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )

        with patch.object(workspace_service, "_dns_txt_contains", AsyncMock(return_value=False)):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspace_service.verify_custom_domain(session, workspace)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIsNone(workspace.custom_domain_verified_at)
        session.flush.assert_not_awaited()


class WorkspaceCustomDomainSchemaTests(IsolatedAsyncioTestCase):
    """The 3 custom-domain fields are exposed on ``WorkspaceRead`` and the
    ``set_custom_domain`` request body is validated (Task 5, schema layer)."""

    async def test_read_exposes_custom_domain_fields(self) -> None:
        from src import schemas

        fields = schemas.WorkspaceRead.model_fields
        for name in ("custom_domain", "custom_domain_verified_at", "custom_domain_verification_token"):
            self.assertIn(name, fields)

    async def test_custom_domain_set_requires_non_empty_string(self) -> None:
        from pydantic import ValidationError

        from src import schemas

        with self.assertRaises(ValidationError):
            schemas.WorkspaceCustomDomainSet(custom_domain="")

        model = schemas.WorkspaceCustomDomainSet(custom_domain="tourney.customer.com")
        self.assertEqual("tourney.customer.com", model.custom_domain)
