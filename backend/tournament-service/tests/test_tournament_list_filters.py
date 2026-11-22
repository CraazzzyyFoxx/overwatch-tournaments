"""DB-backed tests for the server-side tournament list: filters, sort, paging.

Same real-DB skip pattern as ``test_tournament_visibility_reads.py``: the DB is
probed once per test, any connection failure skips cleanly, the suite refuses to
run against production, and the uuid-suffixed workspace is cascade-deleted at the
end.

Five properties that only exist at the SQL level:

1. ``status`` (any of a list) must reach the **count** query as well as the page
   query — a filter missing from the total makes ``total`` describe a different
   set than ``results``, and "load more" is decided by comparing exactly those two;
2. the client's ``fields`` must be ignored, because ``apply_search`` splices each
   entry into ``depth_get_column`` and ILIKEs it (arbitrary column read, 500 on a
   typo) — and because an empty list 400s any search at all;
3. ``participants_count`` (admitted registrations; player rows for a tournament with no registrations)
   is an aggregate, not a column, so it needs its own ORDER BY, and a tournament with nobody admitted
   must sort as 0, not float to the top of a ``desc``;
4. every sort needs the ``id`` tie-breaker: OFFSET/LIMIT over a non-unique key
   may repeat a row across pages and silently drop another;
5. ``per_page=-1`` ("every row") stops at 500 rows, not at the shared 10,000.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.registration import Registration, RegistrationEntry  # noqa: E402
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament import FlowNode, Player, Team, Tournament  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402
from src import schemas  # noqa: E402
from src.services.registration.service import registration_service  # noqa: E402
from src.services.tournament.service import tournament_service  # noqa: E402


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(
        slug=f"list-filters-{suffix}",
        name=f"List Filters {suffix}",
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def _make_tournament(
    session,
    *,
    workspace_id: int,
    name: str,
    status: enums.TournamentStatus = enums.TournamentStatus.ANNOUNCEMENT,
    description: str | None = None,
    start_date: datetime | None = None,
) -> Tournament:
    now = start_date or datetime.now(UTC)
    tournament = Tournament(
        workspace_id=workspace_id,
        name=name,
        # `slug` is NOT NULL and globally unique; production writes go through
        # `generate_unique_tournament_slug`, which this factory bypasses.
        slug=f"{name}-{uuid.uuid4().hex[:8]}",
        description=description,
        status=status,
        is_hidden=False,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    session.add(tournament)
    await session.flush()
    return tournament


async def _add_players(session, *, tournament: Tournament, count: int, user_ids: list[int]) -> None:
    """Seed ``count`` roster rows, i.e. what ``participants_count`` counts.

    A ``Player`` is anchored to a workspace member and a team, both NOT NULL, so
    the aggregate cannot be faked with bare rows.
    """
    if count == 0:
        return
    team = Team(
        name=f"team-{uuid.uuid4().hex[:8]}",
        balancer_name=f"bal-{uuid.uuid4().hex[:8]}",
        tournament_id=tournament.id,
    )
    session.add(team)
    await session.flush()
    for index in range(count):
        user = User(name=f"list-filters-{uuid.uuid4().hex[:12]}")
        session.add(user)
        await session.flush()
        user_ids.append(user.id)
        member = WorkspaceMember(workspace_id=tournament.workspace_id, player_id=user.id)
        session.add(member)
        await session.flush()
        session.add(
            Player(
                name=f"p{index}-{uuid.uuid4().hex[:6]}",
                rank=3000,
                tournament_id=tournament.id,
                workspace_member_id=member.id,
                team_id=team.id,
            )
        )
    await session.flush()


async def _add_registrations(session, *, tournament: Tournament, admitted: int, other: int = 0) -> None:
    """Seed ``admitted`` admitted registrations (checked in, approved, ready) and ``other`` that are not.

    The others each miss exactly one condition, so a dropped clause in the count shows up. One admitted
    registration has a second entry on another node, which must not count it twice.
    """
    node_ids = []
    for position in range(2):
        node = FlowNode(tournament_id=tournament.id, kind="registration", name=f"reg-{position}", status="open")
        session.add(node)
        await session.flush()
        node_ids.append(node.id)
    misses = [
        {"checked_in": False},
        {"status": "pending"},
        {"balancer_status": "not_in_balancer"},
        {"deleted_at": datetime.now(UTC)},
    ]
    specs = [{}] * admitted + [misses[index % len(misses)] for index in range(other)]
    for index, miss in enumerate(specs):
        registration = Registration(tournament_id=tournament.id)
        session.add(registration)
        await session.flush()
        fields = {"checked_in": True, "status": "approved", "balancer_status": "ready", **miss}
        for node_id in node_ids if index == 0 else node_ids[:1]:
            session.add(RegistrationEntry(registration_node_id=node_id, registration_id=registration.id, **fields))
    await session.flush()


async def _cleanup(session_maker, *, workspace_id: int, user_ids: list[int]) -> None:
    async with session_maker() as session:
        # An entry's node FK is RESTRICT, so the entries go before the workspace cascade reaches the nodes.
        await session.execute(
            sa.delete(RegistrationEntry).where(
                RegistrationEntry.registration_id.in_(
                    sa.select(Registration.id)
                    .join(Tournament, Tournament.id == Registration.tournament_id)
                    .where(Tournament.workspace_id == workspace_id)
                )
            )
        )
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        if user_ids:
            # players.user is not workspace-scoped, so the cascade above misses it.
            await session.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def _params(**overrides) -> schemas.TournamentPaginationSortSearchParams:
    fields = overrides.pop("fields", None)
    qp = schemas.TournamentPaginationSortSearchQueryParams(**overrides)
    if fields is not None:
        # Only a client can send this; the model still accepts it, which is the
        # point of the test that it gets discarded.
        qp = qp.model_copy(update={"fields": fields})
    return schemas.TournamentPaginationSortSearchParams.from_query_params(qp)


class _RecordingSession:
    """Captures the statements ``get_all`` builds, so their SQL is assertable
    without a database.

    The DB-backed tests below are the behavioral proof, but they skip wherever
    Postgres is absent (CI sandboxes, a fresh checkout). These four properties
    are visible in the compiled SQL itself, so they get a check that always runs.
    """

    def __init__(self) -> None:
        # Two lists, not one: the page and the total are separate statements
        # issued through separate session methods, and asserting on their SQL
        # must not depend on which of the two the service happens to run first.
        self.page_statements: list[sa.Select] = []
        self.count_statements: list[sa.Select] = []

    async def execute(self, statement):
        self.page_statements.append(statement)
        return self

    async def scalar(self, statement):
        self.count_statements.append(statement)
        return 0

    def unique(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one(self):
        return 0


async def _compiled(**overrides) -> tuple[str, str]:
    """``(page_sql, count_sql)`` for one parameter set, Postgres dialect."""
    from sqlalchemy.dialects import postgresql

    session = _RecordingSession()
    await tournament_service.get_all(session, _params(**overrides))
    (page,) = session.page_statements
    (count,) = session.count_statements
    return (
        str(page.compile(dialect=postgresql.dialect())),
        str(count.compile(dialect=postgresql.dialect())),
    )


def test_sql_puts_the_status_filter_in_both_queries() -> None:
    page_sql, count_sql = asyncio.run(
        _compiled(status=[enums.TournamentStatus.LIVE, enums.TournamentStatus.COMPLETED], per_page=10)
    )

    assert "tournament.status IN " in page_sql
    assert "tournament.status IN " in count_sql


def test_sql_caps_every_row_at_500() -> None:
    from sqlalchemy.dialects import postgresql

    session = _RecordingSession()
    asyncio.run(tournament_service.get_all(session, _params(per_page=-1)))
    (page,) = session.page_statements

    assert "LIMIT 500" in str(page.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_sql_searches_name_even_when_the_client_names_another_column() -> None:
    page_sql, count_sql = asyncio.run(_compiled(query="x", fields=["description", "slug"], per_page=10))

    for sql in (page_sql, count_sql):
        assert "tournament.name ILIKE" in sql
        assert "description ILIKE" not in sql
        assert "slug ILIKE" not in sql


def test_sql_orders_participants_count_by_the_admitted_count() -> None:
    page_sql, _ = asyncio.run(_compiled(sort="participants_count", order="desc", per_page=10))

    # A per-row scalar count, never a NULL-producing outer join: nobody admitted sorts as 0, last on `desc`.
    assert "LEFT OUTER JOIN (SELECT" not in page_sql
    assert "registration_entry.checked_in IS true" in page_sql
    assert "ORDER BY CASE WHEN" in page_sql
    assert "DESC" in page_sql


def test_sql_always_tie_breaks_on_id() -> None:
    for overrides in (
        {"sort": "start_date", "order": "desc"},
        {"sort": "name", "order": "asc"},
        {"sort": "participants_count", "order": "desc"},
    ):
        page_sql, _ = asyncio.run(_compiled(per_page=2, **overrides))
        # Last ORDER BY term, so OFFSET/LIMIT can never repeat or drop a row.
        order_by = page_sql.split("ORDER BY")[1].split("LIMIT")[0].strip()
        assert order_by.endswith("tournament.id DESC"), (overrides, order_by)


def test_status_filter_applies_to_page_and_count() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws = await _make_workspace(session)
                live_a = await _make_tournament(
                    session,
                    workspace_id=ws.id,
                    name=f"live-a-{uuid.uuid4().hex[:8]}",
                    status=enums.TournamentStatus.LIVE,
                )
                live_b = await _make_tournament(
                    session,
                    workspace_id=ws.id,
                    name=f"live-b-{uuid.uuid4().hex[:8]}",
                    status=enums.TournamentStatus.LIVE,
                )
                await _make_tournament(
                    session,
                    workspace_id=ws.id,
                    name=f"reg-{uuid.uuid4().hex[:8]}",
                    status=enums.TournamentStatus.ANNOUNCEMENT,
                )
                await session.commit()
                workspace_id = ws.id
                live_ids = {live_a.id, live_b.id}

            try:
                async with session_maker() as session:
                    unfiltered, unfiltered_total = await tournament_service.get_all(
                        session, _params(workspace_id=workspace_id, per_page=50)
                    )
                    filtered, filtered_total = await tournament_service.get_all(
                        session,
                        _params(workspace_id=workspace_id, per_page=50, status=[enums.TournamentStatus.LIVE]),
                    )
                    either, either_total = await tournament_service.get_all(
                        session,
                        _params(
                            workspace_id=workspace_id,
                            per_page=50,
                            status=[enums.TournamentStatus.LIVE, enums.TournamentStatus.ANNOUNCEMENT],
                        ),
                    )
                return (
                    live_ids,
                    len(unfiltered),
                    unfiltered_total,
                    {row.id for row in filtered},
                    filtered_total,
                    (len(either), either_total),
                    workspace_id,
                )
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id, user_ids=[])

    live_ids, all_rows, all_total, filtered_ids, filtered_total, either, _ = asyncio.run(_run())
    assert all_rows == 3
    assert all_total == 3
    assert filtered_ids == live_ids
    # The count query must see the same filter, or `hasNextPage` lies.
    assert filtered_total == 2
    # Any of several statuses: the header's "running" list in one read.
    assert either == (3, 3)


def test_search_ignores_client_fields_and_matches_name_only() -> None:
    marker = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws = await _make_workspace(session)
                target = await _make_tournament(
                    session,
                    workspace_id=ws.id,
                    name=f"needle-{marker}",
                    description=f"haystack-{marker}",
                )
                await _make_tournament(session, workspace_id=ws.id, name=f"other-{uuid.uuid4().hex[:8]}")
                await session.commit()
                workspace_id, target_id = ws.id, target.id

            try:
                async with session_maker() as session:
                    by_name, by_name_total = await tournament_service.get_all(
                        session, _params(workspace_id=workspace_id, per_page=50, query=f"needle-{marker}")
                    )
                    # A client asking to search `description` must get the server's
                    # answer, not its own.
                    by_desc, by_desc_total = await tournament_service.get_all(
                        session,
                        _params(
                            workspace_id=workspace_id,
                            per_page=50,
                            query=f"haystack-{marker}",
                            fields=["description"],
                        ),
                    )
                return target_id, [r.id for r in by_name], by_name_total, [r.id for r in by_desc], by_desc_total
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id, user_ids=[])

    target_id, name_ids, name_total, desc_ids, desc_total = asyncio.run(_run())
    assert name_ids == [target_id]
    assert name_total == 1
    assert desc_ids == []
    assert desc_total == 0


def test_participants_count_is_the_admitted_count_and_sort_agrees() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            user_ids: list[int] = []
            async with session_maker() as session:
                ws = await _make_workspace(session)
                three = await _make_tournament(session, workspace_id=ws.id, name=f"t3-{uuid.uuid4().hex[:8]}")
                one = await _make_tournament(session, workspace_id=ws.id, name=f"t1-{uuid.uuid4().hex[:8]}")
                none_admitted = await _make_tournament(session, workspace_id=ws.id, name=f"t0-{uuid.uuid4().hex[:8]}")
                legacy = await _make_tournament(session, workspace_id=ws.id, name=f"tl-{uuid.uuid4().hex[:8]}")
                await _add_registrations(session, tournament=three, admitted=3, other=4)
                await _add_registrations(session, tournament=one, admitted=1)
                await _add_registrations(session, tournament=none_admitted, admitted=0, other=4)
                # No registration rows at all: the roster's player rows are the admitted set.
                await _add_players(session, tournament=legacy, count=2, user_ids=user_ids)
                # Player rows next to registrations are not counted: only admission is.
                await _add_players(session, tournament=none_admitted, count=2, user_ids=user_ids)
                await session.commit()
                workspace_id = ws.id
                ids = [three.id, legacy.id, one.id, none_admitted.id]

            try:
                async with session_maker() as session:
                    singles = [await registration_service.get_participants_count_by_tournament(session, i) for i in ids]
                    bulk = await registration_service.get_participants_count_by_tournament_bulk(session, ids)
                    desc, _ = await tournament_service.get_all(
                        session,
                        _params(workspace_id=workspace_id, per_page=50, sort="participants_count", order="desc"),
                    )
                    asc, _ = await tournament_service.get_all(
                        session,
                        _params(workspace_id=workspace_id, per_page=50, sort="participants_count", order="asc"),
                    )
                return ids, singles, bulk, [r.id for r in desc], [r.id for r in asc]
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id, user_ids=user_ids)

    ids, singles, bulk, desc_ids, asc_ids = asyncio.run(_run())
    assert singles == [3, 2, 1, 0]
    assert bulk == dict(zip(ids, singles, strict=True))
    # Nobody admitted sorts last on `desc`, not first.
    assert desc_ids == ids
    assert asc_ids == list(reversed(ids))


def test_pages_do_not_overlap_when_the_sort_key_ties() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            shared_start = datetime.now(UTC)
            async with session_maker() as session:
                ws = await _make_workspace(session)
                created = [
                    (
                        await _make_tournament(
                            session,
                            workspace_id=ws.id,
                            name=f"tie-{index}-{uuid.uuid4().hex[:8]}",
                            start_date=shared_start,
                        )
                    ).id
                    for index in range(4)
                ]
                await session.commit()
                workspace_id = ws.id

            try:
                async with session_maker() as session:
                    pages = []
                    for page in (1, 2):
                        rows, total = await tournament_service.get_all(
                            session,
                            _params(
                                workspace_id=workspace_id,
                                per_page=2,
                                page=page,
                                sort="start_date",
                                order="desc",
                            ),
                        )
                        pages.append(([row.id for row in rows], total))
                return created, pages
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id, user_ids=[])

    created, pages = asyncio.run(_run())
    (page_1, total_1), (page_2, total_2) = pages
    assert total_1 == total_2 == 4
    assert len(page_1) == len(page_2) == 2
    # Four identical start_dates: without the id tie-breaker Postgres may hand the
    # same row back on both pages and never show one of the others.
    assert not set(page_1) & set(page_2)
    assert set(page_1) | set(page_2) == set(created)
