"""The real roster RPC boundary: provider-scoped identities, admission, RBAC and exact wire cutover."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import uuid4

for root in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared import models  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.core.social import SocialProvider, normalize_social_handle  # noqa: E402
from shared.models.identity.rbac import Role, user_roles  # noqa: E402
from shared.services.ontology import project_disciplines  # noqa: E402
from shared.services.social_identity import social_identity_service  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from src.rpc import players  # noqa: E402
from src.services import workspace_roster  # noqa: E402


class _Broker:
    def __init__(self):
        self.handlers = {}

    def subscriber(self, subject):
        def register(fn):
            self.handlers[subject] = fn
            return fn

        return register


class RosterIdentityTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        # The LoL ranked-position ontology is not ambient test-DB state: project it like the other DB tests do.
        await project_disciplines(self.session)
        self.workspace = models.Workspace(
            slug=f"identity-{uuid4().hex}", name="Identity", disciplines_enabled=["overwatch", "lol"]
        )
        self.session.add(self.workspace)
        await self.session.flush()
        self.host = models.AuthUser(username=f"host-{uuid4().hex}", email=f"{uuid4().hex}@example.test")
        self.session.add(self.host)
        await self.session.flush()

    async def asyncTearDown(self):
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _player(self, name, **fields):
        player = models.User(name=f"{name}-{uuid4().hex[:8]}", **fields)
        self.session.add(player)
        await self.session.flush()
        return player

    async def _account(self, player, provider, handle, **fields):
        return await social_identity_service.upsert(
            self.session, user_id=player.id, provider=provider, username=handle, **fields
        )

    async def _call(self, subject, *, host_only=False, member_manager=False, query=None, path_id=None, **body):
        broker = _Broker()
        logger = SimpleNamespace(exception=lambda *a, **k: None, warning=lambda *a, **k: None)
        players.register(broker, logger)

        @asynccontextmanager
        async def factory():
            yield self.session

        identity = {
            "user_id": self.host.id,
            "is_superuser": False,
            "is_active": True,
            "roles": [],
            "permissions": [],
            "workspaces": [
                {
                    "workspace_id": self.workspace.id,
                    "role": "host" if host_only else "admin",
                    "rbac_roles": ["host" if host_only else "admin"],
                    "rbac_permissions": [
                        {"resource": "custom_game", "action": "create"},
                        *([] if host_only else [{"resource": "team", "action": "create"}]),
                        *([{"resource": "workspace_member", "action": "create"}] if member_manager else []),
                    ],
                }
            ],
        }
        with patch.object(players, "_SF", factory):
            return await broker.handlers[subject](
                {
                    "workspace_id": self.workspace.id,
                    "id": path_id,
                    "identity": identity,
                    "payload": body,
                    "query": query or {},
                },
                None,
            )

    async def test_lol_rpc_normalizes_reuses_real_player_and_keeps_verification_unset(self):
        handle = f"Riot Name {uuid4().hex[:6]}#EUW"
        body = {"discipline": "lol", "identity": {"provider": "riot", "handle": f"  {handle.replace('#', ' # ')}  "}}
        response = await self._call("rpc.balancer.players.upsert", host_only=True, **body)
        assert response["ok"], response
        row = response["data"]
        assert row["identity"] == {"provider": "riot", "handle": handle}
        assert "battle_tag" not in row
        player = await self.session.get(models.User, row["player_id"])
        account = await social_identity_service.find_by_handle(self.session, provider="riot", username=handle)
        member = await self.session.get(models.WorkspaceMember, row["member_id"])
        assert player.auth_user_id is None and player.name == handle
        assert account.user_id == player.id and account.is_primary and not account.is_verified
        assert account.provider_user_id is None and member.observed_only is False
        again = await self._call(
            "rpc.balancer.players.upsert",
            host_only=True,
            discipline="lol",
            identity={"provider": "riot", "handle": handle.lower()},
        )
        assert again["ok"] and again["data"]["member_id"] == member.id
        assert again["data"]["player_id"] == player.id

    async def test_real_conflict_and_provider_format_checks_write_nothing(self):
        handle = f"Collision {uuid4().hex[:5]}#EUW"
        for name in ("one", "two"):
            await self._account(await self._player(name), "riot", handle)
        before = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(models.WorkspaceMember)
            .where(models.WorkspaceMember.workspace_id == self.workspace.id)
        )
        for discipline, provider, entered, code, status in [
            ("lol", "battlenet", "Valid#1234", "identity.provider_mismatch", 422),
            ("lol", "riot", "missing-tag", "identity.riot.format", 422),
            ("lol", "riot", handle, "identity_conflict", 409),
        ]:
            with self.assertRaises(ApiHTTPException) as caught:
                await workspace_roster.ensure_member_for_identity(
                    self.session,
                    workspace_id=self.workspace.id,
                    discipline=discipline,
                    provider=provider,
                    handle=entered,
                    admit_account_holders=False,
                )
            assert caught.exception.status_code == status
            assert caught.exception.detail[0]["code"] == code
        after = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(models.WorkspaceMember)
            .where(models.WorkspaceMember.workspace_id == self.workspace.id)
        )
        assert before == after == 0
        self.workspace.disciplines_enabled = ["overwatch"]
        await self.session.flush()
        response = await self._call(
            "rpc.balancer.players.upsert", discipline="lol", identity={"provider": "riot", "handle": handle}
        )
        assert not response["ok"] and "discipline_not_enabled" in response["error"]["message"]

    async def test_observation_anchor_is_hidden_until_real_admission_and_verified_account_is_unchanged(self):
        player = await self._player("observed")
        handle = f"Observed {uuid4().hex[:5]}#EUW"
        account = await self._account(player, "riot", handle, is_verified=True, provider_user_id=uuid4().hex)
        subject = account.provider_user_id
        member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=player.id, observed_only=True)
        self.session.add(member)
        await self.session.flush()
        rows, total = await workspace_roster.roster_page(self.session, workspace_id=self.workspace.id, provider="riot")
        assert not rows and total == 0
        admitted = await workspace_roster.ensure_member_for_identity(
            self.session,
            workspace_id=self.workspace.id,
            discipline="lol",
            provider="riot",
            handle=handle.lower(),
            admit_account_holders=False,
        )
        assert admitted.id == member.id and admitted.observed_only is False
        assert account.username == handle and account.is_verified and account.provider_user_id == subject
        assert player.auth_user_id is None
        rows, total = await workspace_roster.roster_page(self.session, workspace_id=self.workspace.id, provider="riot")
        assert total == 1 and rows[0].identity.handle == handle

    async def test_each_owner_provider_selects_its_own_primary_and_normalized_search(self):
        player = await self._player("both")
        marker = uuid4().hex[:6]
        await self._account(player, "battlenet", f"Battle{marker}#1234")
        await self._account(player, "riot", f"Riot Name {marker}#EUW")
        await self._account(player, "riot", f"Riot Alt {marker}#KR1")
        missing = await self._player("other-game-only")
        await self._account(missing, "battlenet", f"Only{marker}#1234")
        for person in (player, missing):
            self.session.add(models.WorkspaceMember(workspace_id=self.workspace.id, player_id=person.id))
        await self.session.flush()
        lol = await self._call("rpc.balancer.players.list", query={"discipline": "lol"})
        assert lol["ok"], lol
        by_player = {r["player_id"]: r for r in lol["data"]["results"]}
        assert by_player[player.id]["identity"] == {"provider": "riot", "handle": f"Riot Name {marker}#EUW"}
        assert by_player[missing.id]["identity"] is None
        rows, total = await workspace_roster.roster_page(
            self.session, workspace_id=self.workspace.id, provider="riot", search=f"RIOT NAME {marker} # EUW"
        )
        assert total == 1 and rows[0].player_id == player.id
        rows, total = await workspace_roster.roster_page(
            self.session, workspace_id=self.workspace.id, provider="riot", search=f"Battle{marker}#1234"
        )
        assert total == 0
        rows = await workspace_roster.list_roster(
            self.session,
            workspace_id=self.workspace.id,
            provider="battlenet",
            member_ids=[r["member_id"] for r in by_player.values()],
        )
        assert all(r.identity.provider == SocialProvider.BATTLENET for r in rows.values())

    async def test_rank_write_names_its_game_and_reads_default_to_the_first_enabled(self):
        player = await self._player("ranked")
        member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=player.id)
        self.session.add(member)
        await self.session.flush()

        async def write(**body):
            return await self._call("rpc.balancer.players.set_ranks", path_id=member.id, scope="author", **body)

        async def own_book(query):
            listed = await self._call("rpc.balancer.players.list", query=query)
            assert listed["ok"], listed
            return {row["member_id"]: row["author_ranks"] for row in listed["data"]["results"]}[member.id]

        omitted = await write(ranks={"support": 2500})
        assert not omitted["ok"] and omitted["error"]["code"] == "unprocessable", omitted
        assert omitted["error"]["details"]["fields"][0]["field"] == "discipline"
        unknown = await write(discipline="valorant", ranks={"support": 2500})
        assert not unknown["ok"] and "discipline_not_enabled" in unknown["error"]["message"], unknown
        assert await own_book({}) == {}
        assert await own_book({"discipline": "lol"}) == {}

        # Same role code in both games: each write lands on the game it names.
        for discipline, value in (("lol", 3300), ("overwatch", 1600)):
            written = await write(discipline=discipline, ranks={"support": value})
            assert written["ok"] and written["data"] == {"ranks": {"support": value}}, written
        # Reads still default to the workspace's first enabled game (overwatch).
        assert await own_book({}) == {"support": 1600}
        assert await own_book({"discipline": "lol"}) == {"support": 3300}

    async def test_old_wire_is_forbidden_and_mix_host_cannot_rename_existing_member(self):
        handle = f"Existing {uuid4().hex[:5]}#EUW"
        member = await workspace_roster.ensure_member_for_identity(
            self.session,
            workspace_id=self.workspace.id,
            discipline="lol",
            provider="riot",
            handle=handle,
            admit_account_holders=False,
            display_name="Original",
        )
        response = await self._call(
            "rpc.balancer.players.upsert",
            host_only=True,
            discipline="lol",
            identity={"provider": "riot", "handle": handle},
            display_name="Hijacked",
        )
        assert not response["ok"] and response["error"]["code"] == "forbidden"
        await self.session.refresh(member)
        assert member.display_name == "Original"
        response = await self._call(
            "rpc.balancer.players.upsert",
            discipline="lol",
            identity={"provider": "riot", "handle": handle},
            battle_tag="Legacy#1234",
        )
        assert not response["ok"] and response["error"]["code"] == "unprocessable"
        assert response["error"]["details"]["fields"][0]["field"] == "battle_tag"

    async def test_display_name_never_proves_identity_and_riot_export_uses_exact_accounts(self):
        from src.services.team_export.identity import find_users_by_handles

        handle = f"Named {uuid4().hex[:5]}#EUW"
        unrelated = models.User(name=handle)
        self.session.add(unrelated)
        await self.session.flush()
        member = await workspace_roster.ensure_member_for_identity(
            self.session,
            workspace_id=self.workspace.id,
            discipline="lol",
            provider="riot",
            handle=handle,
            admit_account_holders=False,
        )
        assert member.player_id != unrelated.id
        player = await self.session.get(models.User, member.player_id)
        tag = hashlib.sha1(normalize_social_handle("riot", handle).encode()).hexdigest()[:8]  # noqa: S324 - a label
        assert player.name == f"{handle} (riot:{tag})"
        resolved = await find_users_by_handles(self.session, [handle, unrelated.name.split("#")[0]], provider="riot")
        assert resolved[handle].id == member.player_id
        assert unrelated.name.split("#")[0] not in resolved

    # ── R5: a typed handle of an account holder is no admission ticket ──────────

    async def _account_holder(self, label):
        auth = models.AuthUser(username=f"{label}-{uuid4().hex}", email=f"{uuid4().hex}@example.test")
        self.session.add(auth)
        await self.session.flush()
        player = await self._player(label, auth_user_id=auth.id)
        handle = f"Holder {uuid4().hex[:6]}#EUW"
        account = await self._account(player, "riot", handle, is_verified=True, provider_user_id=uuid4().hex)
        return player, handle, account

    async def _membership(self, player):
        return await self.session.scalar(
            sa.select(models.WorkspaceMember).where(
                models.WorkspaceMember.workspace_id == self.workspace.id,
                models.WorkspaceMember.player_id == player.id,
            )
        )

    async def _workspace_roles(self, player):
        joined = user_roles.join(Role, Role.id == user_roles.c.role_id)
        query = sa.select(Role.name).select_from(joined)
        return sorted(
            await self.session.scalars(
                query.where(user_roles.c.user_id == player.auth_user_id, Role.workspace_id == self.workspace.id)
            )
        )

    async def _host_adds(self, handle, **kwargs):
        return await self._call(
            "rpc.balancer.players.upsert",
            host_only=True,
            discipline="lol",
            identity={"provider": "riot", "handle": handle},
            **kwargs,
        )

    def _assert_refused(self, response):
        assert not response["ok"] and response["error"]["code"] == "forbidden", response
        assert response["error"]["details"]["fields"][0]["field"] == "identity.handle"

    async def test_a_mix_host_cannot_enrol_an_account_holder(self):
        player, handle, account = await self._account_holder("holder")
        before = (account.user_id, account.username, account.is_verified, account.provider_user_id)
        self._assert_refused(await self._host_adds(handle))
        assert await self._membership(player) is None
        assert await self._workspace_roles(player) == []
        await self.session.refresh(account)
        assert (account.user_id, account.username, account.is_verified, account.provider_user_id) == before

    async def test_a_member_manager_admits_an_account_holder_with_the_baseline_role(self):
        player, handle, _account = await self._account_holder("admitted")
        response = await self._host_adds(handle, member_manager=True)
        assert response["ok"], response
        member = await self._membership(player)
        assert member.id == response["data"]["member_id"]
        assert member.observed_only is False and member.removed_at is None
        assert await self._workspace_roles(player) == ["player"]

    async def test_a_mix_host_re_adding_an_admitted_account_holder_is_an_idempotent_hit(self):
        player, handle, _account = await self._account_holder("member")
        member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=player.id)
        self.session.add(member)
        await self.session.flush()
        response = await self._host_adds(handle)
        assert response["ok"], response
        assert response["data"]["member_id"] == member.id
        # An idempotent hit grants nothing: the row was role-less and stays so.
        assert await self._workspace_roles(player) == []

    async def test_a_mix_host_cannot_turn_an_account_holders_observation_anchor_into_a_membership(self):
        player, handle, _account = await self._account_holder("observed")
        anchor = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=player.id, observed_only=True)
        self.session.add(anchor)
        await self.session.flush()
        self._assert_refused(await self._host_adds(handle))
        await self.session.refresh(anchor)
        assert anchor.observed_only is True
        assert await self._workspace_roles(player) == []
