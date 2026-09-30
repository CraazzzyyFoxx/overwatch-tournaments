import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import models, schemas  # noqa: E402
from src.services.auth import auth  # noqa: E402
from src.services.auth_users import auth_users  # noqa: E402
from src.services.players import players  # noqa: E402
from src.services.rbac_admin import (  # noqa: E402
    AuthUserAdminService,
    RoleAdminService,
    auth_user_admin,
    role_admin,
    session_admin,
)
from src.services.rbac_policy import rbac_policy  # noqa: E402
from src.services.sessions import sessions  # noqa: E402
from tests._fakes import FakeSessionCache as _RecordingCache
from tests._fakes import make_root_actor as _root_actor


def _role(
    role_id: int,
    name: str,
    *,
    permissions: list[SimpleNamespace] | None = None,
    is_system: bool = True,
    workspace_id: int | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=role_id,
        name=name,
        description=f"{name} role",
        is_system=is_system,
        workspace_id=workspace_id,
        created_at=now,
        updated_at=None,
        permissions=permissions or [],
    )


def _linked_player(player_id: int, name: str, *, is_primary: bool = True) -> SimpleNamespace:
    """A ``players.user`` row as seen through ``AuthUser.player`` (single-link
    model). ``is_primary`` is accepted for call-site compatibility with the
    historical many-to-many fixture shape but is always True in practice."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=player_id,
        name=name,
        created_at=now,
    )


def _user(
    user_id: int,
    email: str,
    *,
    roles: list[SimpleNamespace],
    player: SimpleNamespace | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    role_names = [role.name for role in roles]
    return SimpleNamespace(
        id=user_id,
        email=email,
        username=email.split("@")[0],
        first_name="Ada",
        last_name="Lovelace",
        avatar_url=None,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        created_at=now,
        updated_at=None,
        roles=roles,
        player=player,
        has_permission=lambda _resource, _action: "admin" in role_names,
    )


class _AdminResult:
    """Covers the ``Result`` access shapes the repository layer uses: the
    ``BaseRepository`` ``unique().scalars().first()`` load, ``scalar_one()`` for a
    COUNT, ``scalar_one_or_none()`` for an EXISTS probe and the row-tuple
    ``all()``."""

    def __init__(self, value) -> None:
        self._value = value

    def unique(self):
        return self

    def scalars(self):
        return SimpleNamespace(first=lambda: self._value, all=lambda: list(self._value or []))

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def all(self):
        return list(self._value or [])


class _AdminQueueSession:
    """Fakes a session whose ``execute``/``scalar`` calls pop from one FIFO of
    canned values, in the repository call order of the flow under test."""

    def __init__(self, results: list | None = None) -> None:
        self._results = list(results or [])
        self.added: list = []
        self.deleted: list = []
        self.commit_called = False
        self.delete_called = False

    async def execute(self, _query):
        assert self._results, "unexpected execute() call"
        return _AdminResult(self._results.pop(0))

    async def scalar(self, _query):
        assert self._results, "unexpected scalar() call"
        return self._results.pop(0)

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def refresh(self, _row) -> None:
        return None

    async def delete(self, row) -> None:
        self.delete_called = True
        self.deleted.append(row)

    async def commit(self) -> None:
        self.commit_called = True


class _RoleGrants:
    """Stands in for ``UserRoleRepository``: the last-admin guard only reads the
    tally, so that is all this exposes."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.counted: list[int] = []

    async def count_for_role(self, _session, role_id: int) -> int:
        self.counted.append(role_id)
        return self._count

    async def user_ids_for_role(self, _session, _role_id: int) -> list[int]:
        return []


def test_list_auth_users_route_returns_user_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_role = _role(1, "admin")
    users = [_user(7, "ada@example.com", roles=[admin_role], player=_linked_player(12, "AdaPlayer"))]

    async def fake_list_with_rbac(session, params, *, include_player=False):
        assert params.search == "ada"
        assert params.role_id == 1
        assert params.is_active is True
        assert params.is_superuser is False
        assert params.page == 2
        assert params.per_page == 25
        assert include_player is True
        return users, 51

    monkeypatch.setattr(auth_users, "list_with_rbac", fake_list_with_rbac)

    response = asyncio.run(
        auth_user_admin.list(
            object(),
            SimpleNamespace(is_superuser=True),
            schemas.AuthUserListParams(
                search="ada", role_id=1, is_active=True, is_superuser=False, page=2, per_page=25
            ),
        )
    )

    assert response["total"] == 51
    assert response["page"] == 2
    assert response["per_page"] == 25
    results = response["results"]
    assert len(results) == 1
    assert results[0].email == "ada@example.com"
    assert results[0].linked_players[0].player_name == "AdaPlayer"
    assert results[0].roles[0].name == "admin"


def test_require_permission_allows_user_with_matching_permission() -> None:
    current_user = SimpleNamespace(
        is_active=True,
        has_permission=lambda resource, action: resource == "role" and action == "read",
    )

    # The guard is a raise-or-pass check now, so "allowed" is "did not raise".
    assert rbac_policy.require_permission(current_user, "role", "read") is None


def test_require_permission_rejects_user_without_matching_permission() -> None:
    current_user = SimpleNamespace(
        is_active=True,
        has_permission=lambda _resource, _action: False,
    )

    with pytest.raises(HTTPException) as exc_info:
        rbac_policy.require_permission(current_user, "role", "update")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied: role.update required"


def test_auth_user_has_permission_allows_admin_role_without_explicit_permissions() -> None:
    current_user = models.AuthUser(
        email="admin@example.com",
        username="admin",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.roles = [models.Role(name="admin")]

    assert current_user.has_permission("player", "create") is True


def test_auth_user_has_permission_allows_cached_admin_role_without_explicit_permissions() -> None:
    current_user = models.AuthUser(
        email="admin@example.com",
        username="admin",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.set_rbac_cache(role_names=["admin"], permissions=[])

    assert current_user.has_permission("team", "create") is True


def test_auth_user_admin_panel_access_rejects_read_only_permissions() -> None:
    current_user = models.AuthUser(
        email="member@example.com",
        username="member",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.set_rbac_cache(
        role_names=[],
        permissions=[{"resource": "tournament", "action": "read"}],
        workspace_rbac={
            7: {
                "roles": ["member"],
                "permissions": [{"resource": "team", "action": "read"}],
            },
        },
    )

    assert current_user.has_admin_panel_access() is False
    assert current_user.has_admin_panel_access(7) is False


def test_auth_user_admin_panel_access_allows_scoped_non_read_permission() -> None:
    current_user = models.AuthUser(
        email="operator@example.com",
        username="operator",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.set_rbac_cache(
        role_names=[],
        permissions=[],
        workspace_rbac={
            8: {
                "roles": ["member"],
                "permissions": [
                    {"resource": "team", "action": "read"},
                    {"resource": "team", "action": "update"},
                ],
            },
        },
    )

    assert current_user.has_admin_panel_access() is True
    assert current_user.has_admin_panel_access(8) is True
    assert current_user.has_admin_panel_access(9) is False


def test_auth_user_admin_panel_access_rejects_custom_game_grants() -> None:
    """Hosting a mix is a member-level capability, not an admin-panel key."""
    current_user = models.AuthUser(
        email="host@example.com",
        username="host",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.set_rbac_cache(
        role_names=[],
        permissions=[],
        workspace_rbac={
            10: {
                "roles": ["member"],
                "permissions": [
                    {"resource": "custom_game", "action": "read"},
                    {"resource": "custom_game", "action": "create"},
                    {"resource": "custom_game", "action": "update"},
                    {"resource": "custom_game", "action": "delete"},
                ],
            },
            11: {
                "roles": ["member"],
                "permissions": [{"resource": "team", "action": "update"}],
            },
        },
    )

    assert current_user.has_admin_panel_access(10) is False
    # The exclusion is per-resource, not a blanket kill of the non-read shortcut.
    assert current_user.has_admin_panel_access(11) is True


def test_auth_user_admin_panel_access_allows_panel_roles() -> None:
    current_user = models.AuthUser(
        email="moderator@example.com",
        username="moderator",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.set_rbac_cache(role_names=["moderator"], permissions=[])

    assert current_user.has_admin_panel_access() is True


def test_get_auth_user_route_returns_effective_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    permissions = [
        SimpleNamespace(resource="team", action="read"),
        SimpleNamespace(resource="team", action="update"),
        SimpleNamespace(resource="*", action="*"),
    ]
    admin_role = _role(1, "admin", permissions=permissions)
    linked_player = _linked_player(42, "GracePlayer")
    user = _user(9, "grace@example.com", roles=[admin_role], player=linked_player)

    async def fake_get_with_rbac(session, user_id, *, include_player=False):
        assert user_id == 9
        assert include_player is True
        return user

    monkeypatch.setattr(auth_users, "get_with_rbac", fake_get_with_rbac)

    response = asyncio.run(
        auth_user_admin.get(
            object(),
            SimpleNamespace(is_superuser=True, has_permission=lambda r, a: True),
            9,
        )
    )

    assert response.email == "grace@example.com"
    assert response.roles[0].name == "admin"
    assert len(response.linked_players) == 1
    assert response.linked_players[0].player_id == 42
    assert response.linked_players[0].player_name == "GracePlayer"
    assert response.linked_players[0].is_primary is True
    assert response.effective_permissions == ["admin.*", "team.read", "team.update"]


def test_get_auth_user_route_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_with_rbac(session, user_id, *, include_player=False):
        assert user_id == 404
        assert include_player is True
        return None

    monkeypatch.setattr(auth_users, "get_with_rbac", fake_get_with_rbac)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_user_admin.get(
                object(),
                SimpleNamespace(is_superuser=True, has_permission=lambda r, a: True),
                404,
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"


def test_get_current_user_info_returns_linked_players(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_role = _role(1, "admin")
    linked_player = _linked_player(42, "GracePlayer")
    user = _user(9, "grace@example.com", roles=[admin_role], player=linked_player)

    async def fake_get_with_rbac(session, user_id, *, include_player=False):
        assert user_id == 9
        assert include_player is True
        return user

    async def fake_workspace_rbac_for_user(session, user_id, ws_ids):
        assert user_id == 9
        assert list(ws_ids) == []
        return {}

    class _WorkspaceRows:
        @staticmethod
        def all():
            return []

    class _SessionStub:
        @staticmethod
        async def execute(_query):
            return _WorkspaceRows()

    monkeypatch.setattr(auth_users, "get_with_rbac", fake_get_with_rbac)
    monkeypatch.setattr(auth.roles, "workspace_rbac_for_user", fake_workspace_rbac_for_user)

    response = asyncio.run(auth.get_me(_SessionStub(), 9))

    assert response.email == "grace@example.com"
    assert len(response.linked_players) == 1
    assert response.linked_players[0].player_id == 42
    assert response.linked_players[0].player_name == "GracePlayer"
    assert response.linked_players[0].is_primary is True


def test_list_auth_sessions_route_returns_superuser_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)

    async def fake_list_all_sessions(session, *, user_id=None, search=None, status=None):
        assert user_id == 12
        assert search == "ada"
        assert status == "active"
        return [
            {
                "session_id": "session-1",
                "user_id": 12,
                "email": "ada@example.com",
                "username": "ada",
                "status": "active",
                "login_at": now,
                "last_seen_at": now,
                "expires_at": now,
                "revoked_at": None,
                "user_agent": "Chrome",
                "ip_address": "10.0.0.1",
            }
        ]

    monkeypatch.setattr(sessions, "list_all_sessions", fake_list_all_sessions)

    response = asyncio.run(
        session_admin.list_auth_sessions(
            object(),
            SimpleNamespace(is_superuser=True),
            schemas.SessionListParams(user_id=12, search="ada", status="active"),
        )
    )

    assert response["total"] == 1
    assert response["page"] == 1
    results = response["results"]
    assert len(results) == 1
    assert results[0].session_id == "session-1"
    assert results[0].email == "ada@example.com"


def test_list_auth_sessions_route_sorts_and_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def _summary(session_id: str, hours: int) -> dict:
        seen = base.replace(hour=hours)
        return {
            "session_id": session_id,
            "user_id": 1,
            "email": f"{session_id}@example.com",
            "username": session_id,
            "status": "active",
            "login_at": seen,
            "last_seen_at": seen,
            "expires_at": seen,
            "revoked_at": None,
            "user_agent": "Chrome",
            "ip_address": "10.0.0.1",
        }

    summaries = [_summary("s1", 1), _summary("s2", 2), _summary("s3", 3)]

    async def fake_list_all_sessions(session, *, user_id=None, search=None, status=None):
        return list(summaries)

    monkeypatch.setattr(sessions, "list_all_sessions", fake_list_all_sessions)

    # last_seen_at desc, page 1 of size 2 -> newest two sessions.
    response = asyncio.run(
        session_admin.list_auth_sessions(
            object(),
            SimpleNamespace(is_superuser=True),
            schemas.SessionListParams(page=1, per_page=2, sort="last_seen_at", order="desc"),
        )
    )

    assert response["total"] == 3
    ids = [row.session_id for row in response["results"]]
    assert ids == ["s3", "s2"]

    # page 2 -> the remaining oldest session.
    response_page2 = asyncio.run(
        session_admin.list_auth_sessions(
            object(),
            SimpleNamespace(is_superuser=True),
            schemas.SessionListParams(page=2, per_page=2, sort="last_seen_at", order="desc"),
        )
    )

    assert response_page2["total"] == 3
    assert [row.session_id for row in response_page2["results"]] == ["s1"]


def test_assign_linked_player_to_auth_user_route_calls_admin_link_service(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(9, "grace@example.com", roles=[])
    session = _AdminQueueSession(results=[user])

    async def fake_admin_link(link_session, auth_user_id, player_id, is_primary):
        assert link_session is session
        assert auth_user_id == 9
        assert player_id == 42
        assert is_primary is False
        return SimpleNamespace()

    monkeypatch.setattr(players, "admin_link", fake_admin_link)

    response = asyncio.run(
        auth_user_admin.assign_linked_player(
            session,
            _root_actor(),
            9,
            SimpleNamespace(player_id=42, is_primary=False),
        )
    )

    assert response is None


def test_remove_linked_player_from_auth_user_route_calls_admin_unlink_service(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(9, "grace@example.com", roles=[])
    session = _AdminQueueSession(results=[user])

    async def fake_admin_unlink(link_session, auth_user_id, player_id):
        assert link_session is session
        assert auth_user_id == 9
        assert player_id == 42
        return None

    monkeypatch.setattr(players, "admin_unlink", fake_admin_unlink)

    response = asyncio.run(
        auth_user_admin.remove_linked_player(
            session,
            _root_actor(),
            9,
            42,
        )
    )

    assert response is None


def test_remove_role_route_blocks_removing_last_admin_assignment() -> None:
    admin_role = _role(1, "admin")
    current_user = _user(1, "root@example.com", roles=[admin_role])
    current_user.is_superuser = True

    grants = _RoleGrants(1)
    service = RoleAdminService(role_grants=grants, cache=_RecordingCache())
    # execute() order in remove_from_user: target user (with roles), then the role.
    session = _AdminQueueSession(results=[current_user, admin_role])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.remove_from_user(
                session,
                current_user,
                SimpleNamespace(user_id=1, role_id=1),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot remove the last admin role assignment"
    assert grants.counted == [1]
    assert session.commit_called is False


def test_remove_role_route_allows_admin_removal_when_another_assignment_exists() -> None:
    admin_role = _role(1, "admin")
    current_user = _user(1, "root@example.com", roles=[admin_role])
    current_user.is_superuser = True

    grants = _RoleGrants(2)
    cache = _RecordingCache()
    service = RoleAdminService(role_grants=grants, cache=cache)
    session = _AdminQueueSession(results=[current_user, admin_role])

    asyncio.run(
        service.remove_from_user(
            session,
            current_user,
            SimpleNamespace(user_id=1, role_id=1),
        )
    )

    assert grants.counted == [1]
    assert session.commit_called is True
    assert current_user.roles == []
    assert cache.invalidated == [1]


def test_update_role_route_rejects_system_roles() -> None:
    system_role = _role(11, "moderator", is_system=True)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            role_admin.update(
                _AdminQueueSession(results=[system_role]),
                SimpleNamespace(is_superuser=True),
                11,
                SimpleNamespace(name="moderator_v2", description=None, permission_ids=None),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot modify system roles"


def test_delete_role_route_rejects_system_roles() -> None:
    system_role = _role(12, "admin", is_system=True)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            role_admin.delete(
                _AdminQueueSession(results=[system_role]),
                SimpleNamespace(is_superuser=True),
                12,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot delete system roles"


def test_delete_oauth_connection_route_deletes_connection() -> None:
    auth_user = SimpleNamespace(id=11, username="linked-user", hashed_password="hashed")
    connection = SimpleNamespace(
        id=21,
        provider="discord",
        auth_user_id=11,
        auth_user=auth_user,
    )

    session = _AdminQueueSession(results=[connection])

    asyncio.run(
        auth_user_admin.delete_oauth_connection(
            session,
            _root_actor(),
            21,
        )
    )

    assert session.deleted == [connection]
    assert session.commit_called is True


def test_delete_oauth_connection_route_blocks_last_passwordless_login() -> None:
    auth_user = SimpleNamespace(id=15, username="oauth-only", hashed_password=None)
    connection = SimpleNamespace(
        id=31,
        provider="twitch",
        auth_user_id=15,
        auth_user=auth_user,
    )

    # execute() order: the connection with its auth user, then the COUNT of the
    # user's remaining connections (1 -> this is the last one).
    session = _AdminQueueSession(results=[connection, 1])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_user_admin.delete_oauth_connection(
                session,
                SimpleNamespace(id=1, is_superuser=True, has_permission=lambda r, a: True),
                31,
            )
        )

    assert exc_info.value.status_code == 400
    assert (
        exc_info.value.detail == "Cannot unlink last OAuth provider for a passwordless account. Set a password first."
    )
    assert session.delete_called is False
    assert session.commit_called is False


def test_delete_auth_user_route_deletes_and_invalidates() -> None:
    target = SimpleNamespace(id=9, username="grace", email="grace@example.com")

    cache = _RecordingCache()
    service = AuthUserAdminService(cache=cache)
    session = _AdminQueueSession(results=[target])

    asyncio.run(
        service.delete(
            session,
            SimpleNamespace(id=1, username="root", email="root@example.com", is_superuser=True),
            9,
        )
    )

    assert session.deleted == [target]
    assert session.commit_called is True
    assert cache.invalidated == [9]


def test_delete_auth_user_route_blocks_self_delete() -> None:
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_user_admin.delete(
                object(),
                SimpleNamespace(id=7, is_superuser=True),
                7,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot delete your own account"


def test_delete_auth_user_route_requires_superuser() -> None:
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_user_admin.delete(
                object(),
                SimpleNamespace(id=1, is_superuser=False),
                9,
            )
        )

    assert exc_info.value.status_code == 403


def test_delete_auth_user_route_raises_not_found() -> None:
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_user_admin.delete(
                _AdminQueueSession(results=[None]),
                SimpleNamespace(id=1, is_superuser=True),
                404,
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"


def test_create_role_route_rejects_reserved_role_names() -> None:
    """``admin`` is a hardcoded full-bypass marker in the shared AuthUser model,
    so minting a self-service role under it (or the other trusted names) would be
    an escalation path. The check is case-insensitive and runs before any write."""
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            role_admin.create(
                object(),
                SimpleNamespace(is_superuser=True),
                SimpleNamespace(name="Admin", description=None, workspace_id=None, permission_ids=None),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Role name 'Admin' is reserved"


def test_create_role_route_blocks_granting_permissions_the_actor_lacks() -> None:
    """Privilege ceiling: ``role.create`` must not let a limited operator mint a
    role more powerful than the operator's own permission set."""
    permission = SimpleNamespace(id=5, name="team.delete", resource="team", action="delete", description=None)
    actor = SimpleNamespace(
        is_superuser=False,
        has_permission=lambda resource, action: (resource, action) == ("role", "create"),
    )
    # Repository order in create: name-uniqueness probe via scalar(), then the
    # requested permissions via execute().
    session = _AdminQueueSession(results=[None, [permission]])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            role_admin.create(
                session,
                actor,
                SimpleNamespace(name="Referees", description=None, workspace_id=None, permission_ids=[5]),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == (
        "Permission denied: cannot grant a role carrying a permission you do not hold (team.delete)"
    )
    assert session.added == []
    assert session.commit_called is False


def test_assign_role_route_requires_workspace_membership() -> None:
    """A workspace role may only be granted to someone who is in that workspace."""
    target = SimpleNamespace(id=9, username="grace", email="grace@example.com", roles=[])
    role = _role(5, "Referees", is_system=False, workspace_id=7)
    # execute(): target user, then the role; scalar(): the membership EXISTS probe.
    session = _AdminQueueSession(results=[target, role, None])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            role_admin.assign_to_user(
                session,
                SimpleNamespace(id=1, username="root", email="root@example.com", is_superuser=True),
                SimpleNamespace(user_id=9, role_id=5),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Target user must be a member of the workspace"
    assert target.roles == []
    assert session.commit_called is False


def test_remove_role_route_blocks_removing_last_workspace_owner() -> None:
    """The workspace-scoped twin of the last-admin guard: a workspace must never
    be left without an owner."""
    owner_role = _role(5, "owner", workspace_id=7)
    target = _user(9, "grace@example.com", roles=[owner_role])
    # execute(): target user, the role, then the workspace owner role lookup;
    # scalar(): "target holds owner", then the owner tally (1 -> the last one).
    session = _AdminQueueSession(results=[target, owner_role, owner_role, True, 1])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            RoleAdminService(cache=_RecordingCache()).remove_from_user(
                session,
                SimpleNamespace(id=1, username="root", email="root@example.com", is_superuser=True),
                SimpleNamespace(user_id=9, role_id=5),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot remove the last workspace owner role assignment"
    assert target.roles == [owner_role]
    assert session.commit_called is False
