"""``get_or_create_workspace_member`` idempotency + ``add_member`` player_id
resolution (real-DB integration; mirrors the identity-service DB-skip pattern
in ``backend/identity-service/tests/test_signup_provisions_player.py``).

Every workspace/player row created here is rolled back at the end of the test
(the session is opened, used, then rolled back — never committed) so the test
leaves no residue in the dev DB. Skips cleanly when the DB is unreachable /
is production.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from shared.models.identity.auth_user import AuthUser
from shared.models.identity.user import User
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.rbac import user_has_any_workspace_role
from shared.repository import get_or_create_workspace_member
from shared.services.division_grid_access import get_default_division_grid_version_id
from src.services.workspace import service as workspace_service


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Probes with ``select current_database()`` (mirrors the app-service ``rpc``
    fixture / identity-service's ``db_session`` fixture) and hard-guards
    against ever running against a production database. The session is never
    committed by these tests, so nothing written here persists.
    """
    from src.core import db as db_module

    async def _probe_and_open():
        session = db_module.async_session_maker()
        dbname = (await session.execute(sa.text("select current_database()"))).scalar()
        return session, dbname

    try:
        session, dbname = asyncio.run(_probe_and_open())
    except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
        pytest.skip(f"database unreachable: {exc}")
        return

    if dbname in {"anak_v5", "anak_prod"}:
        asyncio.run(session.close())
        pytest.skip("refusing to run integration tests against production")
        return

    try:
        yield session
    finally:
        asyncio.run(session.rollback())
        asyncio.run(session.close())


async def _make_player(session, *, auth_user_id: int | None = None) -> User:
    suffix = uuid.uuid4().hex[:12]
    player = User(name=f"wsmember_{suffix}", auth_user_id=auth_user_id)
    session.add(player)
    await session.flush()
    return player


async def _make_auth_user(session) -> AuthUser:
    """Create a real ``auth.user`` so the anchor-trigger autofill (which inserts
    ``auth.user_roles``) has a valid FK target — a fake id would violate it."""
    suffix = uuid.uuid4().hex[:12]
    auth_user = AuthUser(
        email=f"wsm-{suffix}@example.com",
        username=f"wsm_{suffix}",
        hashed_password="x",
    )
    session.add(auth_user)
    await session.flush()
    return auth_user


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    workspace = Workspace(
        slug=f"wsmember-test-{suffix}",
        name=f"WS Member Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


def test_get_or_create_workspace_member_is_idempotent(db_session) -> None:
    async def _run():
        workspace = await _make_workspace(db_session)
        player = await _make_player(db_session)

        first = await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player.id)
        second = await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player.id)
        return first, second

    first, second = asyncio.run(_run())

    assert first.id == second.id
    assert first.workspace_id == second.workspace_id == first.workspace_id
    assert first.player_id == second.player_id == first.player_id


def test_get_or_create_workspace_member_distinct_players_distinct_rows(db_session) -> None:
    async def _run():
        workspace = await _make_workspace(db_session)
        player_a = await _make_player(db_session)
        player_b = await _make_player(db_session)

        member_a = await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player_a.id)
        member_b = await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player_b.id)
        return member_a, member_b

    member_a, member_b = asyncio.run(_run())

    assert member_a.id != member_b.id
    assert member_a.player_id != member_b.player_id


def test_get_members_excludes_players_without_auth_link(db_session) -> None:
    """Regression: workspace_member rows anchored on tournament-only players
    (``players.user.auth_user_id IS NULL`` — created by registration / team /
    draft flows via ``get_or_create_workspace_member``) must NOT appear in the
    RBAC members list.

    Before the fix a single such row made ``rpc.app.workspaces.members_list``
    500 for the whole workspace: ``_member_payload`` -> ``get_member_auth_user_id``
    raised ``"workspace_member N has no linked auth user"`` on the null link,
    poisoning the entire listing.
    """

    async def _run():
        workspace = await _make_workspace(db_session)

        auth_user = await _make_auth_user(db_session)
        linked = await _make_player(db_session, auth_user_id=auth_user.id)
        player_only = await _make_player(db_session, auth_user_id=None)

        await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=linked.id)
        await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player_only.id)

        members = await workspace_service.get_members(db_session, workspace.id)
        return {m.player_id for m in members}, linked.id, player_only.id

    player_ids, linked_id, player_only_id = asyncio.run(_run())

    assert linked_id in player_ids
    assert player_only_id not in player_ids


def test_add_member_creates_row_anchored_on_player_id(db_session) -> None:
    async def _run():
        workspace = await _make_workspace(db_session)
        auth_user = await _make_auth_user(db_session)
        # add_member resolves player_id from auth_user_id via the player link.
        await _make_player(db_session, auth_user_id=auth_user.id)

        member = await workspace_service.add_member(db_session, workspace.id, auth_user.id)
        row = await db_session.execute(sa.select(WorkspaceMember).where(WorkspaceMember.id == member.id))
        # The anchor autofill trigger grants the baseline member role to the
        # new auth-linked member.
        has_role = await user_has_any_workspace_role(db_session, user_id=auth_user.id, workspace_id=workspace.id)
        return member, row.scalar_one(), has_role

    member, row, has_role = asyncio.run(_run())

    assert row.player_id == member.player_id
    assert has_role is True
    assert not hasattr(WorkspaceMember, "auth_user_id")
    assert not hasattr(WorkspaceMember, "role")


def test_add_member_provisions_player_for_authuser_without_one(db_session) -> None:
    """A legacy auth user with no ``players.user`` can still be added: add_member
    provisions a bare player on demand and anchors the membership on it."""

    async def _run():
        workspace = await _make_workspace(db_session)
        auth_user = await _make_auth_user(db_session)  # deliberately no linked player

        member = await workspace_service.add_member(db_session, workspace.id, auth_user.id)
        player = await db_session.get(User, member.player_id)
        return auth_user.id, player.auth_user_id, member.workspace_id

    auth_id, player_auth_id, member_ws = asyncio.run(_run())

    assert player_auth_id == auth_id  # the provisioned player links back to the auth user


def test_assign_default_member_role_if_roleless_is_idempotent(db_session) -> None:
    """Role-less auth user gets ``member``; a second call is a no-op."""
    from shared.rbac import assign_default_member_role_if_roleless

    async def _run():
        workspace = await _make_workspace(db_session)
        auth_user = await _make_auth_user(db_session)

        first = await assign_default_member_role_if_roleless(
            db_session, user_id=auth_user.id, workspace_id=workspace.id
        )
        again = await assign_default_member_role_if_roleless(
            db_session, user_id=auth_user.id, workspace_id=workspace.id
        )
        has = await user_has_any_workspace_role(db_session, user_id=auth_user.id, workspace_id=workspace.id)
        return first, again, has

    first, again, has = asyncio.run(_run())

    assert first is True  # assigned member
    assert again is False  # already has a role -> no-op
    assert has is True


def test_list_members_page_paginates_and_excludes_auth_less(db_session) -> None:
    """``list_members_page`` scopes to auth-linked members, counts them, and
    honours page size."""

    async def _run():
        workspace = await _make_workspace(db_session)
        au1 = await _make_auth_user(db_session)
        au2 = await _make_auth_user(db_session)
        p1 = await _make_player(db_session, auth_user_id=au1.id)
        p2 = await _make_player(db_session, auth_user_id=au2.id)
        orphan = await _make_player(db_session, auth_user_id=None)
        for player in (p1, p2, orphan):
            await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player.id)

        first_total, first_rows = await workspace_service.list_members_page(
            db_session, workspace.id, page=1, per_page=1, search=None
        )
        all_total, all_rows = await workspace_service.list_members_page(
            db_session, workspace.id, page=1, per_page=50, search=None
        )
        return first_total, len(first_rows), all_total, {au.id for (_m, au, _r) in all_rows}, au1.id, au2.id

    first_total, first_len, all_total, auth_ids, au1_id, au2_id = asyncio.run(_run())

    assert first_total == 2  # orphan (auth_user_id NULL) excluded from the count
    assert first_len == 1  # per_page=1 returns one row
    assert all_total == 2
    assert auth_ids == {au1_id, au2_id}


def test_list_members_page_role_filter_and_sort(db_session) -> None:
    """``role_id`` narrows to members holding that role; ``sort='role'`` orders by
    the primary system-role rank (admin before member)."""
    from shared.rbac import assign_workspace_system_role, get_workspace_system_role

    async def _run():
        workspace = await _make_workspace(db_session)
        au_admin = await _make_auth_user(db_session)
        au_member = await _make_auth_user(db_session)
        p_admin = await _make_player(db_session, auth_user_id=au_admin.id)
        p_member = await _make_player(db_session, auth_user_id=au_member.id)
        for player in (p_admin, p_member):
            await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player.id)
        # Both got 'member' via the anchor trigger; promote one to admin.
        await assign_workspace_system_role(
            db_session, user_id=au_admin.id, workspace_id=workspace.id, role_name="admin"
        )
        admin_role = await get_workspace_system_role(db_session, workspace.id, "admin")

        _f_total, f_rows = await workspace_service.list_members_page(
            db_session, workspace.id, page=1, per_page=50, search=None, role_id=admin_role.id
        )
        _s_total, s_rows = await workspace_service.list_members_page(
            db_session, workspace.id, page=1, per_page=50, search=None, sort="role", order="asc"
        )
        return (
            {au.id for (_m, au, _r) in f_rows},
            [au.id for (_m, au, _r) in s_rows],
            au_admin.id,
            au_member.id,
        )

    filtered_ids, sorted_ids, admin_id, member_id = asyncio.run(_run())

    assert filtered_ids == {admin_id}  # role filter keeps only the admin
    assert sorted_ids.index(admin_id) < sorted_ids.index(member_id)  # admin rank < member rank


def test_autofill_member_roles_grants_member_to_roleless(db_session) -> None:
    """``autofill_member_roles`` grants ``member`` to a role-less auth-linked
    member and is idempotent on a second run."""

    async def _run():
        workspace = await _make_workspace(db_session)
        auth_user = await _make_auth_user(db_session)
        player = await _make_player(db_session, auth_user_id=auth_user.id)
        # Insert the member row directly to bypass get_or_create's anchor autofill
        # and simulate a legacy role-less member.
        db_session.add(WorkspaceMember(workspace_id=workspace.id, player_id=player.id))
        await db_session.flush()

        assigned = await workspace_service.autofill_member_roles(db_session, workspace.id)
        assigned_again = await workspace_service.autofill_member_roles(db_session, workspace.id)
        has = await user_has_any_workspace_role(db_session, user_id=auth_user.id, workspace_id=workspace.id)
        return assigned, assigned_again, has

    assigned, assigned_again, has = asyncio.run(_run())

    assert assigned == 1
    assert assigned_again == 0
    assert has is True
