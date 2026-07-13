import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.core.errors import BaseAPIException as HTTPException


def _ensure_test_env() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "auth_test",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "JWT_SECRET_KEY": "test-secret",
        "DISCORD_CLIENT_ID": "discord-client",
        "DISCORD_CLIENT_SECRET": "discord-secret",
        "TWITCH_CLIENT_ID": "twitch-client",
        "TWITCH_CLIENT_SECRET": "twitch-secret",
        "BATTLENET_CLIENT_ID": "battlenet-client",
        "BATTLENET_CLIENT_SECRET": "battlenet-secret",
        "OAUTH_REDIRECT": "http://localhost:3000/auth/callback",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import models, schemas  # noqa: E402
from src.services import auth_flows, auth_service, rbac_flows  # noqa: E402


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


def test_list_auth_users_route_returns_user_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_role = _role(1, "admin")
    users = [_user(7, "ada@example.com", roles=[admin_role], player=_linked_player(12, "AdaPlayer"))]

    async def fake_list_users_with_rbac(session, params, *, include_player_links=False):
        assert params.search == "ada"
        assert params.role_id == 1
        assert params.is_active is True
        assert params.is_superuser is False
        assert params.page == 2
        assert params.per_page == 25
        assert include_player_links is True
        return users, 51

    monkeypatch.setattr(
        "src.services.rbac_flows.auth_service.AuthService.list_users_with_rbac",
        fake_list_users_with_rbac,
    )

    response = asyncio.run(
        rbac_flows.list_auth_users(
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

    dependency = auth_service.require_permission("role", "read")

    response = asyncio.run(dependency(current_user=current_user))

    assert response is current_user


def test_require_permission_rejects_user_without_matching_permission() -> None:
    current_user = SimpleNamespace(
        is_active=True,
        has_permission=lambda _resource, _action: False,
    )

    dependency = auth_service.require_permission("role", "assign")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(dependency(current_user=current_user))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied: role.assign required"


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

    assert current_user.has_permission("team", "import") is True


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


def test_auth_user_admin_panel_access_allows_panel_roles() -> None:
    current_user = models.AuthUser(
        email="organizer@example.com",
        username="organizer",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    current_user.set_rbac_cache(role_names=["tournament_organizer"], permissions=[])

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

    async def fake_get_user_with_rbac(session, user_id, *, include_player_links=False):
        assert user_id == 9
        assert include_player_links is True
        return user

    monkeypatch.setattr(
        "src.services.rbac_flows.auth_service.AuthService.get_user_with_rbac",
        fake_get_user_with_rbac,
    )

    response = asyncio.run(
        rbac_flows.get_auth_user(
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
    async def fake_get_user_with_rbac(session, user_id, *, include_player_links=False):
        assert user_id == 404
        assert include_player_links is True
        return None

    monkeypatch.setattr(
        "src.services.rbac_flows.auth_service.AuthService.get_user_with_rbac",
        fake_get_user_with_rbac,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.get_auth_user(
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

    async def fake_get_user_with_rbac(session, user_id, *, include_player_links=False):
        assert user_id == 9
        assert include_player_links is True
        return user

    async def fake_get_workspace_roles_and_permissions_db(session, user_id, ws_ids):
        assert user_id == 9
        assert ws_ids == []
        return {}

    class _WorkspaceRows:
        @staticmethod
        def all():
            return []

    class _SessionStub:
        @staticmethod
        async def execute(_query):
            return _WorkspaceRows()

    monkeypatch.setattr(
        "src.services.auth_flows.AuthService.get_user_with_rbac",
        fake_get_user_with_rbac,
    )
    monkeypatch.setattr(
        "src.services.auth_flows.AuthService.get_workspace_roles_and_permissions_db",
        fake_get_workspace_roles_and_permissions_db,
    )

    response = asyncio.run(
        auth_flows.get_me(
            session=_SessionStub(),
            user_id=9,
        )
    )

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

    monkeypatch.setattr("src.services.rbac_flows.SessionService.list_all_sessions", fake_list_all_sessions)

    response = asyncio.run(
        rbac_flows.list_auth_sessions(
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

    monkeypatch.setattr("src.services.rbac_flows.SessionService.list_all_sessions", fake_list_all_sessions)

    # last_seen_at desc, page 1 of size 2 -> newest two sessions.
    response = asyncio.run(
        rbac_flows.list_auth_sessions(
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
        rbac_flows.list_auth_sessions(
            object(),
            SimpleNamespace(is_superuser=True),
            schemas.SessionListParams(page=2, per_page=2, sort="last_seen_at", order="desc"),
        )
    )

    assert response_page2["total"] == 3
    assert [row.session_id for row in response_page2["results"]] == ["s1"]


def test_assign_linked_player_to_auth_user_route_calls_admin_link_service(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(9, "grace@example.com", roles=[])

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        async def execute(self, _query):
            return _ScalarResult(user)

    async def fake_admin_link_player(session, auth_user_id, player_id, is_primary):
        assert session is fake_session
        assert auth_user_id == 9
        assert player_id == 42
        assert is_primary is False
        return SimpleNamespace()

    fake_session = _FakeSession()

    monkeypatch.setattr(
        "src.services.rbac_flows.PlayerLinkService.admin_link_player",
        fake_admin_link_player,
    )

    response = asyncio.run(
        rbac_flows.assign_linked_player_to_auth_user(
            fake_session,
            SimpleNamespace(is_superuser=True, has_permission=lambda r, a: True),
            9,
            SimpleNamespace(player_id=42, is_primary=False),
        )
    )

    assert response is None


def test_remove_linked_player_from_auth_user_route_calls_admin_unlink_service(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(9, "grace@example.com", roles=[])

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        async def execute(self, _query):
            return _ScalarResult(user)

    async def fake_admin_unlink_player(session, auth_user_id, player_id):
        assert session is fake_session
        assert auth_user_id == 9
        assert player_id == 42
        return None

    fake_session = _FakeSession()

    monkeypatch.setattr(
        "src.services.rbac_flows.PlayerLinkService.admin_unlink_player",
        fake_admin_unlink_player,
    )

    response = asyncio.run(
        rbac_flows.remove_linked_player_from_auth_user(
            fake_session,
            SimpleNamespace(is_superuser=True, has_permission=lambda r, a: True),
            9,
            42,
        )
    )

    assert response is None


def test_remove_role_route_blocks_removing_last_admin_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    admin_role = _role(1, "admin")
    current_user = _user(1, "root@example.com", roles=[admin_role])
    current_user.is_superuser = True

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        def __init__(self):
            self._values = [current_user, admin_role]
            self.commit_called = False

        async def execute(self, _query):
            return _ScalarResult(self._values.pop(0))

        async def commit(self):
            self.commit_called = True

    async def fake_count_users_with_role(_session, role_id):
        assert role_id == 1
        return 1

    async def fake_invalidate_rbac(_user_id):
        return None

    monkeypatch.setattr("src.services.rbac_flows._count_users_with_role", fake_count_users_with_role, raising=False)
    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.remove_role_from_user(
                session,
                current_user,
                SimpleNamespace(user_id=1, role_id=1),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot remove the last admin role assignment"
    assert session.commit_called is False


def test_remove_role_route_allows_admin_removal_when_another_assignment_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_role = _role(1, "admin")
    current_user = _user(1, "root@example.com", roles=[admin_role])
    current_user.is_superuser = True

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        def __init__(self):
            self._values = [current_user, admin_role]
            self.commit_called = False

        async def execute(self, _query):
            return _ScalarResult(self._values.pop(0))

        async def commit(self):
            self.commit_called = True

    async def fake_count_users_with_role(_session, role_id):
        assert role_id == 1
        return 2

    async def fake_invalidate_rbac(_user_id):
        return None

    monkeypatch.setattr("src.services.rbac_flows._count_users_with_role", fake_count_users_with_role, raising=False)
    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    session = _FakeSession()

    asyncio.run(
        rbac_flows.remove_role_from_user(
            session,
            current_user,
            SimpleNamespace(user_id=1, role_id=1),
        )
    )

    assert session.commit_called is True
    assert current_user.roles == []


def test_update_role_route_rejects_system_roles() -> None:
    system_role = _role(11, "moderator", is_system=True)

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        async def execute(self, _query):
            return _ScalarResult(system_role)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.update_role(
                _FakeSession(),
                SimpleNamespace(is_superuser=True),
                11,
                SimpleNamespace(name="moderator_v2", description=None, permission_ids=None),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot modify system roles"


def test_delete_role_route_rejects_system_roles() -> None:
    system_role = _role(12, "admin", is_system=True)

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        async def execute(self, _query):
            return _ScalarResult(system_role)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.delete_role(
                _FakeSession(),
                SimpleNamespace(is_superuser=True),
                12,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot delete system roles"


def test_delete_oauth_connection_route_deletes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_user = SimpleNamespace(id=11, username="linked-user", hashed_password="hashed")
    connection = SimpleNamespace(
        id=21,
        provider="discord",
        auth_user_id=11,
        auth_user=auth_user,
    )

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        def __init__(self):
            self.commit_called = False
            self.deleted: list[object] = []

        async def execute(self, _query):
            return _ScalarResult(connection)

        async def delete(self, value):
            self.deleted.append(value)

        async def commit(self):
            self.commit_called = True

    session = _FakeSession()

    asyncio.run(
        rbac_flows.delete_oauth_connection(
            session,
            SimpleNamespace(id=1, is_superuser=True, has_permission=lambda r, a: True),
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

    class _ScalarValues:
        def __init__(self, values):
            self._values = values

        def all(self):
            return self._values

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            return _ScalarValues(self._value)

    class _FakeSession:
        def __init__(self):
            self._values = [connection, [31]]
            self.commit_called = False
            self.delete_called = False

        async def execute(self, _query):
            return _ScalarResult(self._values.pop(0))

        async def delete(self, _value):
            self.delete_called = True

        async def commit(self):
            self.commit_called = True

    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.delete_oauth_connection(
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


def test_delete_auth_user_route_deletes_and_invalidates(monkeypatch: pytest.MonkeyPatch) -> None:
    target = SimpleNamespace(id=9, email="grace@example.com")

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        def __init__(self):
            self.commit_called = False
            self.deleted: list[object] = []

        async def execute(self, _query):
            return _ScalarResult(target)

        async def delete(self, value):
            self.deleted.append(value)

        async def commit(self):
            self.commit_called = True

    invalidated: list[int] = []

    async def fake_invalidate_rbac(user_id):
        invalidated.append(user_id)

    monkeypatch.setattr("src.services.rbac_flows.invalidate_rbac", fake_invalidate_rbac, raising=False)

    session = _FakeSession()

    asyncio.run(
        rbac_flows.delete_auth_user(
            session,
            SimpleNamespace(id=1, is_superuser=True),
            9,
        )
    )

    assert session.deleted == [target]
    assert session.commit_called is True
    assert invalidated == [9]


def test_delete_auth_user_route_blocks_self_delete() -> None:
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.delete_auth_user(
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
            rbac_flows.delete_auth_user(
                object(),
                SimpleNamespace(id=1, is_superuser=False),
                9,
            )
        )

    assert exc_info.value.status_code == 403


def test_delete_auth_user_route_raises_not_found() -> None:
    class _ScalarResult:
        def scalar_one_or_none(self):
            return None

    class _FakeSession:
        async def execute(self, _query):
            return _ScalarResult()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rbac_flows.delete_auth_user(
                _FakeSession(),
                SimpleNamespace(id=1, is_superuser=True),
                404,
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"
