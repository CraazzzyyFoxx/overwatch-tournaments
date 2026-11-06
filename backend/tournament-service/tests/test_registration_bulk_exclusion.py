from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.errors import BaseAPIException as HTTPException
from src.services.registration.lifecycle import lifecycle_service  # noqa: E402


class _TournamentResult:
    """``ensure_tournament_exists`` now goes through ``TournamentRepository.get``,
    which reads ``result.unique().scalars().first()``."""

    def __init__(self, tournament: SimpleNamespace) -> None:
        self._tournament = tournament

    def unique(self) -> _TournamentResult:
        return self

    def scalars(self) -> _TournamentResult:
        return self

    def first(self) -> SimpleNamespace:
        return self._tournament


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[SimpleNamespace]:
        return self._rows


def _entry(registration_id: int, *, status: str, ranked: bool) -> SimpleNamespace:
    registration = SimpleNamespace(
        id=registration_id,
        tournament_id=7,
        roles=[SimpleNamespace(is_active=True, rank_value=2500 if ranked else None)],
    )
    return SimpleNamespace(
        registration=registration,
        registration_id=registration_id,
        registration_node_id=5,
        status=status,
        exclude_reason=None,
        balancer_status="incomplete",
    )


def _session(*execute_results: object) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(side_effect=list(execute_results)),
        scalar=AsyncMock(return_value=7),
        commit=AsyncMock(),
        info={},
    )


class BulkSetBalancerStatusTests(IsolatedAsyncioTestCase):
    async def test_excluded_only_touches_the_rows_the_query_returns(self) -> None:
        """ "excluded" (like every non-not_in_balancer target) filters to
        approved rows at the SQL level -- this fake session can't express
        that filter, so it only hands back the row that would actually match."""
        approved = _entry(1, status="approved", ranked=True)
        tournament = SimpleNamespace(workspace_id=99)
        session = _session(_TournamentResult(tournament), _Result([approved]))

        updated, skipped = await lifecycle_service.bulk_set_balancer_status(
            session,
            5,
            [1, 404],
            balancer_status="excluded",
            exclude_reason="manual_exclusion",
        )

        self.assertEqual((1, 1), (updated, skipped))
        self.assertEqual("excluded", approved.balancer_status)
        self.assertEqual("manual_exclusion", approved.exclude_reason)
        session.commit.assert_awaited_once()

    async def test_not_in_balancer_does_not_require_approved_and_clears_reason(self) -> None:
        approved = _entry(1, status="approved", ranked=True)
        pending = _entry(2, status="pending", ranked=False)
        approved.balancer_status = "ready"
        approved.exclude_reason = None
        tournament = SimpleNamespace(workspace_id=99)
        session = _session(_TournamentResult(tournament), _Result([approved, pending]))

        updated, skipped = await lifecycle_service.bulk_set_balancer_status(
            session,
            5,
            [1, 2],
            balancer_status="not_in_balancer",
            exclude_reason="ignored",
        )

        self.assertEqual((2, 0), (updated, skipped))
        self.assertEqual("not_in_balancer", approved.balancer_status)
        self.assertEqual("not_in_balancer", pending.balancer_status)
        # exclude_reason is only meaningful for "excluded" -- always cleared otherwise.
        self.assertIsNone(approved.exclude_reason)
        self.assertIsNone(pending.exclude_reason)
        session.commit.assert_awaited_once()

    async def test_rejects_auto_managed_statuses_outright(self) -> None:
        session = _session()
        with self.assertRaises(HTTPException):
            await lifecycle_service.bulk_set_balancer_status(session, 5, [1], balancer_status="ready")
        session.execute.assert_not_awaited()
