"""DB-backed tests for hidden-tournament visibility gating (issue #115).

Mirrors the real-DB skip pattern of ``test_registration_self_register_gate.py``:
the DB is probed once per test; any connection failure skips cleanly, and the
tests refuse to run against a production database. Throwaway uuid-suffixed
workspaces/tournaments are cleaned up (cascade) at the end.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _ensure_test_env() -> None:
    env = {
        "DEBUG": "true",
        "PROJECT_URL": "http://localhost",
        "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
        "REDIS_URL": "redis://localhost:6379/0",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "anak_dev",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPreviewAccess  # noqa: E402
from shared.services.division_grid_access import get_default_division_grid_version_id  # noqa: E402
from shared.services.tournament_visibility import assert_tournament_viewable  # noqa: E402
from src import schemas  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402


@asynccontextmanager
async def _db_sessions():
    """Yield a fresh per-test session factory, or skip if the DB is unreachable.

    Pooled asyncpg connections are bound to the event loop that created them,
    so the module-global engine cannot be shared across ``asyncio.run()``
    calls: each test gets its own NullPool engine, created and disposed inside
    the test's single event loop. Probes with ``select current_database()``
    and hard-guards against ever running against a production database.
    """
    from src.core import config

    engine = create_async_engine(config.settings.db_url_asyncpg, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as conn:
                dbname = (await conn.execute(sa.text("select current_database()"))).scalar()
        except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
            pytest.skip(f"database unreachable: {exc}")
        if dbname in {"anak_v5", "anak_prod"}:
            pytest.skip("refusing to run integration tests against production")
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    workspace = Workspace(
        slug=f"hidden-test-{suffix}",
        name=f"Hidden Vis Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def _make_tournament(session, *, workspace_id: int, is_hidden: bool) -> Tournament:
    suffix = uuid.uuid4().hex[:12]
    # ``TournamentRead.start_date``/``end_date`` are required datetimes, so the
    # list serializer (``flows.get_all``) rejects rows seeded without dates.
    now = datetime.now(UTC)
    tournament = Tournament(
        workspace_id=workspace_id,
        name=f"Hidden Vis Tournament {suffix}",
        status=enums.TournamentStatus.DRAFT,
        is_hidden=is_hidden,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    session.add(tournament)
    await session.flush()
    return tournament


async def _make_auth_user(session, suffix: str) -> AuthUser:
    auth_user = AuthUser(
        email=f"hidden-{suffix}@example.com",
        username=f"hidden_{suffix}",
        hashed_password="x",
    )
    session.add(auth_user)
    await session.flush()
    return auth_user


def _viewer(auth_user_id: int, *, superuser: bool = False, ws_admin: list[int] | None = None) -> AuthUser:
    user = AuthUser()
    user.id = auth_user_id
    user.is_superuser = superuser
    user.is_active = True
    ws_admin = ws_admin or []
    ws_rbac = {ws: {"roles": [], "permissions": [{"resource": "*", "action": "*"}]} for ws in ws_admin}
    user.set_rbac_cache(
        role_names=[],
        permissions=[],
        workspaces=[{"workspace_id": w} for w in ws_admin],
        workspace_rbac=ws_rbac,
    )
    return user


async def _cleanup(session_maker, *, workspace_id: int) -> None:
    async with session_maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


def test_assert_viewable_matrix() -> None:
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws = await _make_workspace(session)
                hidden = await _make_tournament(session, workspace_id=ws.id, is_hidden=True)
                visible = await _make_tournament(session, workspace_id=ws.id, is_hidden=False)
                allow_user = await _make_auth_user(session, suffix)
                await session.commit()
                workspace_id = ws.id
                hidden_id, visible_id, allow_user_id = hidden.id, visible.id, allow_user.id

            try:
                async with session_maker() as session:
                    # allowlist allow_user for the hidden tournament
                    session.add(
                        TournamentPreviewAccess(tournament_id=hidden_id, auth_user_id=allow_user_id)
                    )
                    await session.commit()

                    results: dict[str, object] = {}

                    # not hidden -> anyone (even anon) sees it
                    await assert_tournament_viewable(session, None, visible_id)
                    results["visible_anon"] = "ok"

                    # hidden + anon -> 404
                    try:
                        await assert_tournament_viewable(session, None, hidden_id)
                        results["hidden_anon"] = "leak"
                    except BaseAPIException as exc:
                        results["hidden_anon"] = exc.status_code

                    # hidden + superuser -> ok
                    await assert_tournament_viewable(session, _viewer(999999, superuser=True), hidden_id)
                    results["hidden_superuser"] = "ok"

                    # hidden + workspace admin -> ok
                    await assert_tournament_viewable(
                        session, _viewer(999998, ws_admin=[workspace_id]), hidden_id
                    )
                    results["hidden_ws_admin"] = "ok"

                    # hidden + allowlisted -> ok
                    await assert_tournament_viewable(session, _viewer(allow_user_id), hidden_id)
                    results["hidden_allowlisted"] = "ok"

                    # hidden + non-allowlisted logged-in user -> 404
                    try:
                        await assert_tournament_viewable(session, _viewer(999997), hidden_id)
                        results["hidden_outsider"] = "leak"
                    except BaseAPIException as exc:
                        results["hidden_outsider"] = exc.status_code

                return results
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    results = asyncio.run(_run())
    assert results["visible_anon"] == "ok"
    assert results["hidden_anon"] == 404
    assert results["hidden_superuser"] == "ok"
    assert results["hidden_ws_admin"] == "ok"
    assert results["hidden_allowlisted"] == "ok"
    assert results["hidden_outsider"] == 404


def test_list_excludes_hidden_for_anonymous() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws = await _make_workspace(session)
                hidden = await _make_tournament(session, workspace_id=ws.id, is_hidden=True)
                visible = await _make_tournament(session, workspace_id=ws.id, is_hidden=False)
                await session.commit()
                workspace_id = ws.id
                hidden_id, visible_id = hidden.id, visible.id

            try:
                async with session_maker() as session:
                    qp = schemas.TournamentPaginationSortSearchQueryParams(
                        workspace_id=workspace_id, per_page=100
                    )
                    params = schemas.TournamentPaginationSortSearchParams.from_query_params(qp)

                    anon_page = await tournament_flows.get_all(session, params, viewer=None)
                    super_page = await tournament_flows.get_all(
                        session, params, viewer=_viewer(1, superuser=True)
                    )
                    anon_ids = {r.id for r in anon_page.results}
                    super_ids = {r.id for r in super_page.results}

                return hidden_id, visible_id, anon_ids, super_ids
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    hidden_id, visible_id, anon_ids, super_ids = asyncio.run(_run())
    assert visible_id in anon_ids
    assert hidden_id not in anon_ids
    assert hidden_id in super_ids
