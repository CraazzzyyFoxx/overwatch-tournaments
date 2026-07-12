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
from pathlib import Path

import pytest
import sqlalchemy as sa


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


@pytest.fixture
def db_session():
    from src.core import db as db_module

    async def _probe_and_open():
        session = db_module.async_session_maker()
        dbname = (await session.execute(sa.text("select current_database()"))).scalar()
        return session, dbname

    try:
        session, dbname = asyncio.run(_probe_and_open())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
        return

    if dbname in {"anak_v5", "anak_prod"}:
        asyncio.run(session.close())
        pytest.skip("refusing to run integration tests against production")
        return

    try:
        yield session
    finally:
        asyncio.run(session.close())


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
    tournament = Tournament(
        workspace_id=workspace_id,
        name=f"Hidden Vis Tournament {suffix}",
        status=enums.TournamentStatus.DRAFT,
        is_hidden=is_hidden,
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


async def _cleanup(session, *, workspace_id: int) -> None:
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_assert_viewable_matrix(db_session) -> None:
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        ws = await _make_workspace(db_session)
        hidden = await _make_tournament(db_session, workspace_id=ws.id, is_hidden=True)
        visible = await _make_tournament(db_session, workspace_id=ws.id, is_hidden=False)
        allow_user = await _make_auth_user(db_session, suffix)
        await db_session.commit()

        # allowlist allow_user for the hidden tournament
        db_session.add(TournamentPreviewAccess(tournament_id=hidden.id, auth_user_id=allow_user.id))
        await db_session.commit()

        results: dict[str, object] = {}

        # not hidden -> anyone (even anon) sees it
        await assert_tournament_viewable(db_session, None, visible.id)
        results["visible_anon"] = "ok"

        # hidden + anon -> 404
        try:
            await assert_tournament_viewable(db_session, None, hidden.id)
            results["hidden_anon"] = "leak"
        except BaseAPIException as exc:
            results["hidden_anon"] = exc.status_code

        # hidden + superuser -> ok
        await assert_tournament_viewable(db_session, _viewer(999999, superuser=True), hidden.id)
        results["hidden_superuser"] = "ok"

        # hidden + workspace admin -> ok
        await assert_tournament_viewable(db_session, _viewer(999998, ws_admin=[ws.id]), hidden.id)
        results["hidden_ws_admin"] = "ok"

        # hidden + allowlisted -> ok
        await assert_tournament_viewable(db_session, _viewer(allow_user.id), hidden.id)
        results["hidden_allowlisted"] = "ok"

        # hidden + non-allowlisted logged-in user -> 404
        try:
            await assert_tournament_viewable(db_session, _viewer(999997), hidden.id)
            results["hidden_outsider"] = "leak"
        except BaseAPIException as exc:
            results["hidden_outsider"] = exc.status_code

        return ws.id, results

    try:
        workspace_id, results = asyncio.run(_run())
        assert results["visible_anon"] == "ok"
        assert results["hidden_anon"] == 404
        assert results["hidden_superuser"] == "ok"
        assert results["hidden_ws_admin"] == "ok"
        assert results["hidden_allowlisted"] == "ok"
        assert results["hidden_outsider"] == 404
    finally:
        asyncio.run(_cleanup(db_session, workspace_id=workspace_id))


def test_list_excludes_hidden_for_anonymous(db_session) -> None:
    async def _run():
        ws = await _make_workspace(db_session)
        hidden = await _make_tournament(db_session, workspace_id=ws.id, is_hidden=True)
        visible = await _make_tournament(db_session, workspace_id=ws.id, is_hidden=False)
        await db_session.commit()

        qp = schemas.TournamentPaginationSortSearchQueryParams(workspace_id=ws.id, per_page=100)
        params = schemas.TournamentPaginationSortSearchParams.from_query_params(qp)

        anon_page = await tournament_flows.get_all(db_session, params, viewer=None)
        super_page = await tournament_flows.get_all(db_session, params, viewer=_viewer(1, superuser=True))
        return ws.id, hidden.id, visible.id, anon_page, super_page

    try:
        workspace_id, hidden_id, visible_id, anon_page, super_page = asyncio.run(_run())
        anon_ids = {r.id for r in anon_page.results}
        super_ids = {r.id for r in super_page.results}
        assert visible_id in anon_ids
        assert hidden_id not in anon_ids
        assert hidden_id in super_ids
    finally:
        asyncio.run(_cleanup(db_session, workspace_id=workspace_id))
