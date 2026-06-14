"""Tests for workspace-aware balancer auth dependencies."""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src import models  # noqa: E402
from src.core import auth  # noqa: E402
from src.routes.admin import draft as draft_route  # noqa: E402


def _make_user() -> models.AuthUser:
    return models.AuthUser(
        id=1,
        username="tester",
        email="tester@example.com",
        is_active=True,
        is_superuser=False,
    )


class WorkspaceAuthDependencyTests(IsolatedAsyncioTestCase):
    async def test_token_resolver_populates_workspace_rbac_cache(self) -> None:
        user = await auth._resolve_user_from_token(  # type: ignore[attr-defined]
            42,
            {
                "username": "member",
                "email": "member@example.com",
                "roles": [],
                "permissions": [],
                "workspaces": [
                    {
                        "workspace_id": 7,
                        "slug": "ws-7",
                        "role": "member",
                        "rbac_roles": ["editor"],
                        "rbac_permissions": [{"resource": "team", "action": "import"}],
                    }
                ],
            },
        )

        self.assertTrue(user.is_workspace_member(7))
        self.assertEqual(user.get_workspace_role(7), "member")
        self.assertTrue(user.has_workspace_permission(7, "team", "import"))
        self.assertFalse(user.has_workspace_permission(8, "team", "import"))

    async def test_tournament_permission_allows_workspace_scoped_access(self) -> None:
        user = _make_user()
        user.set_rbac_cache(
            role_names=[],
            permissions=[],
            workspaces=[{"workspace_id": 9, "role": "member"}],
            workspace_rbac={9: {"roles": [], "permissions": [{"resource": "team", "action": "read"}]}},
        )
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=9)

        checker = auth.require_tournament_permission("team", "read")
        result = await checker(tournament_id=55, session=session, current_user=user)

        self.assertIs(result, user)

    async def test_tournament_permission_rejects_legacy_organizer_without_permission(self) -> None:
        user = _make_user()
        user.set_rbac_cache(
            role_names=["tournament_organizer"],
            permissions=[],
            workspaces=[],
            workspace_rbac={},
        )
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=9)

        checker = auth.require_tournament_permission("team", "read")

        with self.assertRaises(HTTPException) as ctx:
            await checker(tournament_id=55, session=session, current_user=user)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_tournament_permission_allows_workspace_wildcard(self) -> None:
        user = _make_user()
        user.set_rbac_cache(
            role_names=[],
            permissions=[],
            workspaces=[{"workspace_id": 9, "role": "admin"}],
            workspace_rbac={9: {"roles": ["owner"], "permissions": [{"resource": "*", "action": "*"}]}},
        )
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=9)

        checker = auth.require_tournament_permission("team", "import")
        result = await checker(tournament_id=55, session=session, current_user=user)

        self.assertIs(result, user)

    async def test_tournament_permission_rejects_missing_workspace_access(self) -> None:
        user = _make_user()
        user.set_rbac_cache(
            role_names=[],
            permissions=[],
            workspaces=[{"workspace_id": 9, "role": "member"}],
            workspace_rbac={9: {"roles": [], "permissions": []}},
        )
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=9)

        checker = auth.require_tournament_permission("team", "read")

        with self.assertRaises(HTTPException) as ctx:
            await checker(tournament_id=55, session=session, current_user=user)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_draft_select_route_uses_authenticated_user_dependency(self) -> None:
        user_dependency = inspect.signature(draft_route.select_route).parameters["user"].default.dependency

        self.assertIs(user_dependency, auth.get_current_active_user)
