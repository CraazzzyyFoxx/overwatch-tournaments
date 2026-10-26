"""``resolve_active_user`` must hand back a user whose RBAC is actually readable.

The regression this pins: ``_resolve_bearer`` loads the row through
``get_identity`` -- ``noload(AuthUser.roles)`` -- whenever the Redis RBAC entry
is warm, and nothing then attached the cached RBAC to the instance. ``noload``
yields an EMPTY collection instead of raising, so every ``has_permission`` /
``has_workspace_permission`` on the resolved user answered False without an
error anywhere. A superuser survived (that is a column on the row); a workspace
owner got 403 across the whole RBAC admin surface -- Access > Roles simply
failed to load -- and only until the cache expired, which is why it looked
intermittent.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from src.services.token_payload import TokenPayloadBuilder  # noqa: E402
from src.services.token_validation import TokenValidationService  # noqa: E402
from tests._fakes import FakeSessionCache  # noqa: E402

WORKSPACE = 11


class _ExplodingRepo:
    """Any repository call means the cached entry was not trusted."""

    def __getattr__(self, name):
        async def _fail(*args, **kwargs):
            raise AssertionError(f"a full RBAC cache hit must not call {name}()")

        return _fail


class _ExplodingSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("a full RBAC cache hit must not touch the database")


class _IdentityOnlyUsers:
    """``get_identity`` as the repository really behaves: no roles on the row."""

    def __init__(self, user: models.AuthUser) -> None:
        self.user = user

    async def get_identity(self, session, user_id, **kwargs) -> models.AuthUser:
        assert self.user.roles == [], "the point of this fixture is an unhydrated row"
        return self.user

    async def get_with_rbac(self, session, user_id, **kwargs) -> models.AuthUser:
        raise AssertionError("a warm cache must take the identity-only path")


_OWNER = {"email": "owner@example.com", "username": "owner", "is_active": True, "is_superuser": False}


def _resolve(entry: dict) -> models.AuthUser:
    entry = {"user": _OWNER, **entry}
    user = models.AuthUser(
        id=7,
        email="owner@example.com",
        username="owner",
        is_active=True,
        is_superuser=False,
    )
    cache = FakeSessionCache(entry)
    repo = _ExplodingRepo()
    service = TokenValidationService(
        codec=SimpleNamespace(decode=lambda _raw: {"sub": "7", "type": "access"}),
        cache=cache,
        users=_IdentityOnlyUsers(user),
        payloads=TokenPayloadBuilder(cache=cache, roles=repo, members=repo, denies=repo),
    )
    return asyncio.run(service.resolve_active_user(_ExplodingSession(), "access-token"))


def test_a_workspace_owner_keeps_their_wildcard_on_a_warm_cache() -> None:
    """The owner's ``*.*`` lives only in the cache entry, so it has to be stamped."""
    resolved = _resolve(
        {
            "roles": [],
            "permissions": [],
            "workspaces": [[WORKSPACE, "ws-eleven"]],
            "workspace_roles": {
                str(WORKSPACE): {"roles": ["owner"], "permissions": [{"resource": "*", "action": "*"}]}
            },
            "denies": [],
        }
    )

    # The two the Access > Roles screen actually asks for.
    assert resolved.has_workspace_permission(WORKSPACE, "role", "read") is True
    assert resolved.has_workspace_permission(WORKSPACE, "permission", "read") is True
    assert resolved.is_workspace_admin(WORKSPACE) is True
    assert resolved.get_workspace_ids() == [WORKSPACE]


def test_a_plain_member_is_still_refused() -> None:
    """Stamping the cache must widen nothing: a read-only grant stays read-only."""
    resolved = _resolve(
        {
            "roles": [],
            "permissions": [],
            "workspaces": [[WORKSPACE, "ws-eleven"]],
            "workspace_roles": {
                str(WORKSPACE): {"roles": ["member"], "permissions": [{"resource": "tournament", "action": "read"}]}
            },
            "denies": [],
        }
    )

    assert resolved.has_workspace_permission(WORKSPACE, "tournament", "read") is True
    assert resolved.has_workspace_permission(WORKSPACE, "role", "read") is False
    assert resolved.has_permission("role", "read") is False


def test_the_deny_overlay_rides_along() -> None:
    """A deny outranks the owner wildcard, so it must survive the same trip."""
    resolved = _resolve(
        {
            "roles": [],
            "permissions": [],
            "workspaces": [[WORKSPACE, "ws-eleven"]],
            "workspace_roles": {
                str(WORKSPACE): {"roles": ["owner"], "permissions": [{"resource": "*", "action": "*"}]}
            },
            "denies": [{"resource": "role", "action": "delete", "workspace_id": None}],
        }
    )

    assert resolved.has_workspace_permission(WORKSPACE, "role", "delete") is False
    assert resolved.has_workspace_permission(WORKSPACE, "role", "update") is True
