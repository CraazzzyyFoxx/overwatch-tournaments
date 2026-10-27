"""Token payload workspace membership: joins through ``players.user`` and
reports the membership's RBAC role names now that ``workspace_member`` stores
neither ``auth_user_id`` nor a denormalized ``role`` (real-DB integration;
mirrors the DB-skip pattern in ``test_signup_provisions_player.py``).

Redis is never initialised in this test process, so the RBAC cache
read/write in ``TokenPayloadBuilder.build`` degrades gracefully to a
DB-only path (see ``session_cache.get_rbac``/``set_rbac`` catching the
``RuntimeError`` from an uninitialised client) — no live Redis required.

The companion unit test at the bottom pins the opposite end: a complete cache
entry must answer the whole payload with no database access at all.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sqlalchemy as sa  # noqa: E402

from shared import models
from shared.rbac import assign_workspace_system_role, ensure_workspace_system_roles  # noqa: E402
from shared.repository import get_or_create_workspace_member  # noqa: E402
from src import schemas  # noqa: E402
from src.services.auth import auth  # noqa: E402
from src.services.token_payload import TokenPayloadBuilder, token_payloads  # noqa: E402


def test_token_payload_includes_workspace_membership_with_rbac_roles(db_session) -> None:
    """A user who is a member of workspace W (via player_id) gets a
    WorkspaceMembership for W carrying the RBAC role names assigned in that
    workspace -- the only role signal that exists.
    """
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        # 1. Register a real auth user -> provisions a linked players.user row
        #    (Phase A: ``auth_users.ensure_player``).
        payload = schemas.UserRegister(
            email=f"tokenws-{suffix}@example.com",
            username=f"tokenws_{suffix}",
            password="Correct-horse-battery1!",
        )
        auth_user = await auth.register(db_session, payload)

        player = (
            await db_session.execute(sa.select(models.User).where(models.User.auth_user_id == auth_user.id))
        ).scalar_one()

        # 2. Create a workspace and anchor a workspace_member row on player_id.
        workspace = models.Workspace(
            slug=f"tokenws-test-{suffix}",
            name=f"Token WS Test {suffix}",
        )
        db_session.add(workspace)
        await db_session.flush()

        await ensure_workspace_system_roles(db_session, workspace.id)
        await get_or_create_workspace_member(db_session, workspace_id=workspace.id, player_id=player.id)

        # 3. Assign the RBAC "admin" system role (workspace_member has no
        #    stored role column any more -- this is the only role signal).
        await assign_workspace_system_role(
            db_session, user_id=auth_user.id, workspace_id=workspace.id, role_name="admin"
        )
        await db_session.commit()

        # 4. Reload with RBAC eagerly loaded (mirrors token-issuance flow) and
        #    build the token payload.
        current_user = await db_session.get(models.AuthUser, auth_user.id)
        token_payload = await token_payloads.build(db_session, current_user)
        # Release the read transaction before asyncio.run closes its owning loop.
        await db_session.close()
        return workspace.id, token_payload

    workspace_id, token_payload = asyncio.run(_run())

    membership = next((m for m in token_payload.workspaces if m.workspace_id == workspace_id), None)
    assert membership is not None, token_payload.workspaces
    assert "admin" in membership.rbac_roles


class _ExplodingSession:
    """Any database access at all fails the cache-hit contract."""

    async def execute(self, *args, **kwargs):
        raise AssertionError("a full RBAC cache hit must not touch the database")

    async def scalar(self, *args, **kwargs):
        raise AssertionError("a full RBAC cache hit must not touch the database")

    async def get(self, *args, **kwargs):
        raise AssertionError("a full RBAC cache hit must not touch the database")


class _ExplodingRepo:
    """Stands in for every repository the builder can reach."""

    def __getattr__(self, name):
        async def _fail(*args, **kwargs):
            raise AssertionError(f"a full RBAC cache hit must not call {name}()")

        return _fail


from tests._fakes import FakeSessionCache as _HitCache


def test_full_cache_hit_answers_the_whole_payload_without_the_database() -> None:
    """Every component in the entry => zero queries and zero rewrites.

    This is the hottest read path in the service (every request the gateway
    forwards lands here), which is why the cached entry is treated as a
    complete answer rather than a head start. Rewriting it on a full hit would
    also extend the TTL that bounds RBAC staleness, so the write must be
    skipped too, not just the reads.
    """
    entry = {
        "user": {"email": "cached@example.com", "username": "cached", "is_active": True, "is_superuser": False},
        "roles": ["user"],
        "permissions": [{"resource": "tournament", "action": "read"}],
        "workspaces": [[11, "ws-eleven"]],
        "workspace_roles": {"11": {"roles": ["admin"], "permissions": [{"resource": "*", "action": "*"}]}},
        "denies": [{"resource": "tournament", "action": "delete", "workspace_id": None}],
    }
    cache = _HitCache(entry)
    repo = _ExplodingRepo()
    builder = TokenPayloadBuilder(cache=cache, roles=repo, members=repo, denies=repo)
    user = SimpleNamespace(id=5, email="cached@example.com", username="cached", is_superuser=False)

    payload = asyncio.run(builder.build(_ExplodingSession(), user))

    assert cache.reads == 1
    assert cache.writes == []

    assert (payload.sub, payload.email, payload.username, payload.is_superuser) == (
        5,
        "cached@example.com",
        "cached",
        False,
    )
    assert payload.roles == ["user"]
    assert payload.permissions == [{"resource": "tournament", "action": "read"}]
    assert payload.denies == [{"resource": "tournament", "action": "delete", "workspace_id": None}]

    # The membership still reaches the payload — from the cache this time, with
    # its workspace-scoped RBAC intact.
    (membership,) = payload.workspaces
    assert (membership.workspace_id, membership.slug) == (11, "ws-eleven")
    assert membership.rbac_roles == ["admin"]
    assert membership.rbac_permissions == [{"resource": "*", "action": "*"}]


def test_a_handed_over_cache_entry_skips_even_the_redis_read() -> None:
    """``cached=`` lets a caller that already read the entry hand it over."""
    entry = {
        "user": {"email": "cached@example.com", "username": "cached", "is_active": True, "is_superuser": False},
        "roles": [],
        "permissions": [],
        "workspaces": [],
        "workspace_roles": {},
        "denies": [],
    }
    cache = _HitCache(entry)
    repo = _ExplodingRepo()
    builder = TokenPayloadBuilder(cache=cache, roles=repo, members=repo, denies=repo)
    user = SimpleNamespace(id=5, email="cached@example.com", username="cached", is_superuser=False)

    payload = asyncio.run(builder.build(_ExplodingSession(), user, cached=entry))

    assert cache.reads == 0
    assert cache.writes == []
    # "member of nothing" is a real answer, not a miss to be reloaded.
    assert payload.workspaces == []
