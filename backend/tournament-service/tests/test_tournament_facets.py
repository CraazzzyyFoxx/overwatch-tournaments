"""Facet counters for the public tournaments page (rpc.tournament.tournaments_facets).

The whole contract of ``get_facets`` is *which filter each of its three queries
leaves out*, and that is visible in the SQL it builds — so the primary tests drive
it with a recording session and assert on the compiled statements plus the schema
assembled from canned rows. Nothing about it needs a database, and the properties
under test are exactly the ones a reviewer cannot eyeball:

* ``by_status`` must NOT carry the status filter, or picking a chip zeroes its
  siblings and the filter becomes a one-way door;
* ``league``/``standard`` must NOT carry the ``is_league`` filter, for the same
  reason;
* ``total``/``live`` must carry NEITHER (nor the search), because the hero states
  a platform fact, not a property of the current selection;
* the visibility predicate and ``workspace_id`` must be on ALL THREE, including
  the unfiltered totals — a hidden tournament that only leaks into ``total`` still
  leaks.

The DB-backed test at the end is the end-to-end confirmation; it skips wherever
Postgres is unavailable, exactly like ``test_tournament_visibility_reads.py``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("DEBUG", "true")

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.services.division_grid.access import get_default_division_grid_version_id  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402

STATUS = enums.TournamentStatus


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows

    def one(self) -> tuple:
        return self._rows[0]


class _RecordingSession:
    """Hands back canned rows per call while keeping every statement built."""

    def __init__(self, results: list[list[tuple]]) -> None:
        self._results = results
        self.statements: list[sa.Select] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Rows(self._results[len(self.statements) - 1])


#: Enough rows to satisfy all three queries: per-status groups, per-is_league
#: groups, then the single (total, live) row.
_DEFAULT_RESULTS = [
    [(STATUS.LIVE, 3), (STATUS.COMPLETED, 30)],
    [(True, 6), (False, 36)],
    [(42, 3)],
]


async def _run_facets(*, results=None, **kwargs):
    session = _RecordingSession(results if results is not None else _DEFAULT_RESULTS)
    facets = await tournament_flows.flows_service.get_facets(session, **kwargs)
    sql = [str(statement.compile(dialect=postgresql.dialect())) for statement in session.statements]
    return facets, sql


async def _run_facet_statements(**kwargs) -> list[sa.Select]:
    """The statements themselves, for assertions that need the bound values."""
    session = _RecordingSession(_DEFAULT_RESULTS)
    await tournament_flows.flows_service.get_facets(session, **kwargs)
    return session.statements


def test_by_status_ignores_its_own_axis_but_keeps_the_others() -> None:
    _, (status_sql, _, _) = asyncio.run(_run_facets(status=STATUS.LIVE, is_league=True, query="cup", workspace_id=4))

    assert "GROUP BY tournament.tournament.status" in status_sql
    # Its own filter must be absent...
    assert "tournament.status = " not in status_sql
    # ...while every other axis stays, so the numbers match the visible list.
    assert "tournament.is_league IS " in status_sql
    assert "tournament.name ILIKE" in status_sql
    assert "tournament.workspace_id = " in status_sql


def test_league_split_ignores_is_league_but_keeps_status_and_search() -> None:
    _, (_, league_sql, _) = asyncio.run(_run_facets(status=STATUS.LIVE, is_league=True, query="cup", workspace_id=4))

    assert "GROUP BY tournament.tournament.is_league" in league_sql
    assert "tournament.is_league IS " not in league_sql
    assert "tournament.status = " in league_sql
    assert "tournament.name ILIKE" in league_sql


def test_totals_ignore_every_filter_but_never_visibility() -> None:
    _, (_, _, totals_sql) = asyncio.run(_run_facets(status=STATUS.LIVE, is_league=True, query="cup", workspace_id=4))

    assert "tournament.status = " not in totals_sql
    assert "tournament.is_league IS " not in totals_sql
    assert "ILIKE" not in totals_sql
    # Scope, however, is not a filter: it is who is allowed to be counted.
    assert "tournament.is_hidden IS false" in totals_sql
    assert "tournament.workspace_id = " in totals_sql
    # `live` is the conditional aggregate over the same unfiltered set.
    assert "FILTER (WHERE" in totals_sql


def test_visibility_predicate_is_on_every_query() -> None:
    _, statements = asyncio.run(_run_facets())

    for sql in statements:
        assert "tournament.is_hidden IS false" in sql, sql


def test_all_statuses_are_present_even_at_zero() -> None:
    facets, _ = asyncio.run(_run_facets())

    assert set(facets.by_status) == set(STATUS)
    assert facets.by_status[STATUS.LIVE] == 3
    assert facets.by_status[STATUS.COMPLETED] == 30
    # Absent groups come back as explicit zeros, so no client re-derives them.
    assert facets.by_status[STATUS.ARCHIVED] == 0
    assert facets.by_status[STATUS.DRAFT] == 0


def test_league_and_standard_come_from_the_boolean_groups() -> None:
    facets, _ = asyncio.run(_run_facets())

    assert facets.league == 6
    assert facets.standard == 36
    assert facets.total == 42
    assert facets.live == 3


def test_missing_league_group_reads_as_zero_not_a_key_error() -> None:
    facets, _ = asyncio.run(_run_facets(results=[[(STATUS.LIVE, 2)], [(False, 2)], [(2, 2)]]))

    assert facets.league == 0
    assert facets.standard == 2


def test_live_counts_playoffs_too() -> None:
    statements = asyncio.run(_run_facet_statements())
    totals = statements[2].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    # Rendered with literals: the hero's "live now" number is the one place a
    # visitor sees group play and bracket play as a single fact.
    assert "status IN ('live', 'playoffs')" in str(totals)


# ─── DB-backed end-to-end confirmation ────────────────────────────────────────


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    workspace = Workspace(
        slug=f"facets-{suffix}",
        name=f"Facets {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def _make_tournament(
    session, *, workspace_id: int, status: enums.TournamentStatus, is_league: bool = False, is_hidden: bool = False
) -> Tournament:
    now = datetime.now(UTC)
    suffix = uuid.uuid4().hex[:12]
    tournament = Tournament(
        workspace_id=workspace_id,
        name=f"facets-{suffix}",
        # NOT NULL and globally unique; production writes go through
        # `generate_unique_tournament_slug`, which this factory bypasses.
        slug=f"facets-{suffix}",
        status=status,
        is_league=is_league,
        is_hidden=is_hidden,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    session.add(tournament)
    await session.flush()
    return tournament


def _superuser() -> AuthUser:
    user = AuthUser()
    user.id = 999999
    user.is_superuser = True
    user.is_active = True
    user.set_rbac_cache(role_names=[], permissions=[], workspaces=[], workspace_rbac={})
    return user


def test_facets_over_a_real_workspace() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws = await _make_workspace(session)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.LIVE)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.PLAYOFFS)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.REGISTRATION)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.LIVE, is_league=True)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.LIVE, is_hidden=True)
                await session.commit()
                workspace_id = ws.id

            try:
                async with session_maker() as session:
                    flows = tournament_flows.flows_service
                    anon = await flows.get_facets(session, workspace_id=workspace_id)
                    # Selecting a chip must not collapse the other axes.
                    picked = await flows.get_facets(session, workspace_id=workspace_id, status=STATUS.REGISTRATION)
                    leagues_only = await flows.get_facets(session, workspace_id=workspace_id, is_league=True)
                    superuser = await flows.get_facets(session, workspace_id=workspace_id, viewer=_superuser())
                return anon, picked, leagues_only, superuser
            finally:
                async with session_maker() as session:
                    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
                    await session.commit()

    anon, picked, leagues_only, superuser = asyncio.run(_run())

    # Anonymous: the hidden live tournament is in no counter at all.
    assert anon.total == 4
    assert anon.live == 3  # live + playoffs, hidden one excluded
    assert anon.by_status[STATUS.LIVE] == 2
    assert anon.by_status[STATUS.PLAYOFFS] == 1
    assert anon.by_status[STATUS.REGISTRATION] == 1
    assert (anon.league, anon.standard) == (1, 3)

    # status=registration: by_status is unchanged, league/standard narrow to it.
    assert picked.by_status == anon.by_status
    assert (picked.league, picked.standard) == (0, 1)
    assert (picked.total, picked.live) == (anon.total, anon.live)

    # is_league=true: league/standard are unchanged, by_status narrows.
    assert (leagues_only.league, leagues_only.standard) == (anon.league, anon.standard)
    assert leagues_only.by_status[STATUS.LIVE] == 1
    assert leagues_only.by_status[STATUS.REGISTRATION] == 0
    assert (leagues_only.total, leagues_only.live) == (anon.total, anon.live)

    # A superuser sees the hidden one everywhere.
    assert superuser.total == 5
    assert superuser.live == 4
    assert superuser.by_status[STATUS.LIVE] == 3
