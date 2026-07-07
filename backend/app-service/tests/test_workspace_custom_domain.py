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
from sqlalchemy.exc import IntegrityError

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
    def setUp(self) -> None:
        # Every test below exercises the normalize/token/reset behavior, not
        # the duplicate-claim check (see DuplicateCustomDomainTests for that) —
        # patch the best-effort pre-check to report "no conflict" so these
        # tests don't need a session with a working ``execute``, matching how
        # the DNS tests patch ``_dns_txt_contains`` at the exact seam instead
        # of stubbing the network.
        patcher = patch.object(
            workspace_service._workspace_repo, "get_by_custom_domain_any", AsyncMock(return_value=None)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

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


class DuplicateCustomDomainTests(IsolatedAsyncioTestCase):
    """A domain already claimed by another workspace is a 409, not a 500
    (final-review fix): checked twice — a best-effort pre-check
    (``get_by_custom_domain_any``) AND the authoritative ``IntegrityError``
    catch around the write, since the pre-check alone has a TOCTOU gap.
    """

    async def test_pre_check_rejects_domain_claimed_by_another_workspace(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(id=7)
        other_workspace = _make_workspace(id=99, custom_domain="tourney.customer.com")

        with patch.object(
            workspace_service._workspace_repo,
            "get_by_custom_domain_any",
            AsyncMock(return_value=other_workspace),
        ):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspace_service.set_custom_domain(session, workspace, "tourney.customer.com")

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIsNone(workspace.custom_domain)  # never written
        session.flush.assert_not_awaited()

    async def test_pre_check_allows_repointing_the_same_workspaces_own_domain(self) -> None:
        session = SimpleNamespace(flush=AsyncMock())
        workspace = _make_workspace(id=7, custom_domain="tourney.customer.com")

        with patch.object(
            workspace_service._workspace_repo,
            "get_by_custom_domain_any",
            AsyncMock(return_value=workspace),  # the pre-check finds itself
        ):
            result = await workspace_service.set_custom_domain(session, workspace, "tourney.customer.com")

        self.assertIs(result, workspace)
        session.flush.assert_awaited_once()

    async def test_integrity_error_on_write_maps_to_409_and_rolls_back(self) -> None:
        # The pre-check passes (no conflict seen), but the unique index still
        # raises at flush time — the race the pre-check alone cannot close.
        session = SimpleNamespace(
            flush=AsyncMock(
                side_effect=IntegrityError(
                    "UPDATE workspace ...",
                    {},
                    Exception('duplicate key value violates unique constraint "ix_workspace_custom_domain"'),
                )
            ),
            rollback=AsyncMock(),
        )
        workspace = _make_workspace(id=7)

        with patch.object(workspace_service._workspace_repo, "get_by_custom_domain_any", AsyncMock(return_value=None)):
            with self.assertRaises(workspace_service.HTTPException) as ctx:
                await workspace_service.set_custom_domain(session, workspace, "tourney.customer.com")

        self.assertEqual(409, ctx.exception.status_code)
        session.rollback.assert_awaited_once()


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
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )

        with patch.object(workspace_service, "_dns_txt_contains", AsyncMock(return_value=True)) as dns_check:
            result = await workspace_service.verify_custom_domain(session, workspace)

        self.assertIs(result, workspace)
        dns_check.assert_awaited_once_with("_owt-verify.tourney.customer.com", "owt-verify-abc123")
        self.assertIsInstance(workspace.custom_domain_verified_at, datetime)
        session.flush.assert_awaited_once()
        # The read-only transaction is committed (releasing the pooled
        # connection) BEFORE the DNS round-trip, not after.
        session.commit.assert_awaited_once()

    async def test_dns_lookup_runs_after_releasing_the_connection(self) -> None:
        """Regression test for the DNS-outside-transaction fix: ``session.commit()``
        must happen before ``_dns_txt_contains`` runs, not interleaved with or
        after it, so the network round-trip never pins a pooled connection."""
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
        workspace = _make_workspace(
            custom_domain="tourney.customer.com",
            custom_domain_verification_token="owt-verify-abc123",
        )
        call_order: list[str] = []
        session.commit.side_effect = lambda: call_order.append("commit")

        async def _fake_dns_check(*_args: object) -> bool:
            call_order.append("dns")
            return True

        with patch.object(workspace_service, "_dns_txt_contains", _fake_dns_check):
            await workspace_service.verify_custom_domain(session, workspace)

        self.assertEqual(["commit", "dns"], call_order)

    async def test_dns_no_match_raises_400_and_does_not_stamp(self) -> None:
        session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
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
        session.commit.assert_awaited_once()  # still committed the read before the (failed) lookup


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
