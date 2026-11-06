"""Facet counters for the public tournaments page (rpc.tournament.tournaments_facets).

The whole contract of ``get_facets`` is *which filter each of its three queries
leaves out*, and that is visible in the SQL it builds — so the primary tests drive
it with a recording session and assert on the compiled statements plus the schema
assembled from canned rows. Nothing about it needs a database, and the properties
under test are exactly the ones a reviewer cannot eyeball:

* ``by_status`` must NOT carry the status filter, or picking a chip zeroes its
  siblings and the filter becomes a one-way door;
* ``total``/``live`` must carry NO filter (nor the search), because the hero states
  a platform fact, not a property of the current selection;
* the visibility predicate and ``workspace_id`` must be on ALL THREE, including
  the unfiltered totals — a hidden tournament that only leaks into ``total`` still
  leaks.

The DB-backed test at the end is the end-to-end confirmation; it skips wherever
Postgres is unavailable, exactly like ``test_tournament_visibility_reads.py``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import FlowNode, Stage, Tournament  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402
from tests.encounter_seed import seed_scoring_rule  # noqa: E402

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


#: Enough rows to satisfy all three queries: per-status groups, then the single (total, live) row.
_DEFAULT_RESULTS = [
    [(STATUS.LIVE, 3), (STATUS.COMPLETED, 30)],
    [(42, 3)],
    [(5,)],
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
    _, (status_sql, _, _) = asyncio.run(_run_facets(status=STATUS.LIVE, query="cup", workspace_id=4))

    assert "GROUP BY tournament.tournament.status" in status_sql
    # Its own filter must be absent...
    assert "tournament.status = " not in status_sql
    # ...while every other axis stays, so the numbers match the visible list.
    assert "tournament.name ILIKE" in status_sql
    assert "tournament.workspace_id = " in status_sql


def test_totals_ignore_every_filter_but_never_visibility() -> None:
    _, (_, totals_sql, _) = asyncio.run(_run_facets(status=STATUS.LIVE, query="cup", workspace_id=4))

    # Only the "live" aggregate reads the status; no user filter does.
    assert totals_sql.count("tournament.status = ") == 1
    assert "ILIKE" not in totals_sql
    # Scope, however, is not a filter: it is who is allowed to be counted.
    assert "tournament.is_hidden IS false" in totals_sql
    assert "tournament.workspace_id = " in totals_sql
    # `live` is the conditional aggregate over the same unfiltered set.
    assert "FILTER (WHERE" in totals_sql


def test_registration_open_counts_registering_tournaments_under_search_but_not_status() -> None:
    facets, (_, _, registration_sql) = asyncio.run(_run_facets(status=STATUS.LIVE, query="cup", workspace_id=4))

    assert facets.registration_open == 5
    assert "tournament.flow_node.status IN" in registration_sql
    assert "tournament.name ILIKE" in registration_sql
    assert "tournament.status = " not in registration_sql


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
    assert facets.by_status[STATUS.ANNOUNCEMENT] == 0


def test_total_and_live_come_from_the_unfiltered_row() -> None:
    facets, _ = asyncio.run(_run_facets())

    assert facets.total == 42
    assert facets.live == 3


def test_in_play_counts_a_live_tournament_with_a_live_stage_node() -> None:
    statements = asyncio.run(_run_facet_statements())
    totals = statements[1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    # Rendered with literals: the hero's "live now" number is a ball in play, not a registration filling up.
    sql = str(totals)
    assert "tournament.status = 'live'" in sql
    assert "flow_node.kind = 'stage'" in sql
    assert "flow_node.status = 'live'" in sql


# ─── DB-backed end-to-end confirmation ────────────────────────────────────────


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(
        slug=f"facets-{suffix}",
        name=f"Facets {suffix}",
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def _make_tournament(
    session,
    *,
    workspace_id: int,
    status: enums.TournamentStatus,
    is_hidden: bool = False,
    in_play: bool = False,
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
        is_hidden=is_hidden,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    session.add(tournament)
    await session.flush()
    if in_play:
        stage = Stage(
            tournament_id=tournament.id,
            name="S",
            stage_type=enums.StageType.ROUND_ROBIN,
            scoring_rule_id=await seed_scoring_rule(session, workspace_id),
        )
        session.add(stage)
        await session.flush()
        session.add(
            FlowNode(tournament_id=tournament.id, kind="stage", name="S", status="live", stage_id=stage.id, config={})
        )
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
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.LIVE, in_play=True)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.LIVE)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.ANNOUNCEMENT)
                await _make_tournament(session, workspace_id=ws.id, status=STATUS.LIVE, is_hidden=True, in_play=True)
                await session.commit()
                workspace_id = ws.id

            try:
                async with session_maker() as session:
                    flows = tournament_flows.flows_service
                    anon = await flows.get_facets(session, workspace_id=workspace_id)
                    # Selecting a chip must not collapse the other axes.
                    picked = await flows.get_facets(session, workspace_id=workspace_id, status=STATUS.ANNOUNCEMENT)
                    superuser = await flows.get_facets(session, workspace_id=workspace_id, viewer=_superuser())
                return anon, picked, superuser
            finally:
                async with session_maker() as session:
                    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
                    await session.commit()

    anon, picked, superuser = asyncio.run(_run())

    # Anonymous: the hidden live tournament is in no counter at all.
    assert anon.total == 3
    assert anon.live == 1  # live with a live stage node, hidden one excluded; the node-less live one is not in play
    assert anon.by_status[STATUS.LIVE] == 2
    assert anon.by_status[STATUS.ANNOUNCEMENT] == 1

    # status=announcement: by_status is unchanged, the hero totals too.
    assert picked.by_status == anon.by_status
    assert (picked.total, picked.live) == (anon.total, anon.live)

    # A superuser sees the hidden one everywhere.
    assert superuser.total == 4
    assert superuser.live == 2
    assert superuser.by_status[STATUS.LIVE] == 3
