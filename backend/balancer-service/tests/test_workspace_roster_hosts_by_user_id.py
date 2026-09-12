"""Integration tests for ``workspace_roster.hosts_by_user_id``.

Regression for a 500 on ``rpc.balancer.custom.transfer_host``: the picker let a
host hand a mix off to a workspace member who had never signed in (added by
BattleTag only, ``players.user.auth_user_id IS NULL``). ``hosts_by_user_id``
used to resolve/validate candidates by ``workspace_member.player_id`` (the
``players.user`` id space), so that member's own player id passed the
membership check -- and the write then hit ``custom_game.host_user_id``'s
foreign key to ``auth.user.id``, which the ghost member has none of, raising
an ``IntegrityError`` instead of the 404 the RPC layer meant to return.

``custom_game.host_user_id``/``co_host_user_ids`` and ``member_rank.author_user_id``
are all ``auth.user.id``s, so ``hosts_by_user_id`` must resolve candidates by
each player's linked ``auth_user_id``, not their own ``player_id`` -- and must
never resolve a member with no linked account at all, by any id.

Second regression: the add-players dialog's per-author filter chips
(``rpc.balancer.players.authors``) fell back to ``#<id>`` for any author who
had rank-corrected someone here without ever adding *themselves* as a player/
member of this same workspace -- an admin fixing ranks without playing, the
common case. The join used to be an inner join through
``workspace_member``/``players.user``, dropping that account's row entirely;
it must now resolve every real ``auth.user.id``, falling back through the
workspace membership to the account's own ``username`` when there is none.

Requires a reachable database via POSTGRES_* env vars (use a disposable DB such
as anak_dev -- NEVER production). Skips cleanly if the DB is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for path in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.services import workspace_roster  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402

_UNIQUE = 0


def _uniq() -> int:
    global _UNIQUE
    _UNIQUE += 1
    return _UNIQUE


class HostsByUserIdTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        # psycopg async cannot run on the Proactor loop (Windows default).
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        suffix = f"hosts-by-user-id-{os.getpid()}-{_uniq()}"

        async with self.Session() as session:
            workspace = Workspace(slug=f"ws-{suffix}", name=f"WS {suffix}")
            session.add(workspace)
            await session.flush()

            # Has actually signed in: a real ``auth.user`` linked to their player.
            signed_in_auth = AuthUser(username=f"auth-{suffix}", email=f"auth-{suffix}@example.test")
            # A real account that has never added itself as a player/member of
            # *this* workspace at all -- an admin who only ever corrects other
            # players' ranks here (see ``test_falls_back_to_username_...`` below).
            unrostered_auth = AuthUser(username=f"unrostered-{suffix}", email=f"unrostered-{suffix}@example.test")
            session.add_all([signed_in_auth, unrostered_auth])
            await session.flush()

            signed_in_player = User(name=f"signed-in-{suffix}", auth_user_id=signed_in_auth.id)
            # Added by BattleTag only, never authenticated: no linked account.
            ghost_player = User(name=f"ghost-{suffix}")
            session.add_all([signed_in_player, ghost_player])
            await session.flush()

            signed_in_member = WorkspaceMember(
                workspace_id=workspace.id, player_id=signed_in_player.id, display_name="Signed In"
            )
            ghost_member = WorkspaceMember(workspace_id=workspace.id, player_id=ghost_player.id)
            session.add_all([signed_in_member, ghost_member])
            await session.commit()

            self.workspace_id = workspace.id
            self.signed_in_auth_id = signed_in_auth.id
            self.signed_in_player_id = signed_in_player.id
            self.ghost_player_id = ghost_player.id
            self.unrostered_auth_id = unrostered_auth.id
            self.unrostered_username = unrostered_auth.username

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as session:
            await session.execute(sa.delete(WorkspaceMember).where(WorkspaceMember.workspace_id == self.workspace_id))
            await session.execute(sa.delete(User).where(User.id.in_([self.signed_in_player_id, self.ghost_player_id])))
            await session.execute(
                sa.delete(AuthUser).where(AuthUser.id.in_([self.signed_in_auth_id, self.unrostered_auth_id]))
            )
            await session.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await session.commit()
        await self.engine.dispose()

    async def test_resolves_a_member_by_their_linked_auth_user_id(self) -> None:
        async with self.Session() as session:
            names = await workspace_roster.hosts_by_user_id(
                session, workspace_id=self.workspace_id, user_ids=[self.signed_in_auth_id]
            )
        self.assertEqual(names, {self.signed_in_auth_id: "Signed In"})

    async def test_never_resolves_a_member_with_no_linked_account_even_by_their_own_player_id(self) -> None:
        # The exact shape of the bug: the ghost's own `players.user.id` used to
        # satisfy the (wrongly keyed) membership check `transfer_host` runs
        # before writing `custom_game.host_user_id` -- a column that has no
        # row for this id at all, since the player never signed in.
        async with self.Session() as session:
            names = await workspace_roster.hosts_by_user_id(
                session, workspace_id=self.workspace_id, user_ids=[self.ghost_player_id]
            )
        self.assertEqual(names, {})

    async def test_falls_back_to_username_for_an_author_never_rostered_in_this_workspace(self) -> None:
        async with self.Session() as session:
            names = await workspace_roster.hosts_by_user_id(
                session, workspace_id=self.workspace_id, user_ids=[self.unrostered_auth_id]
            )
        self.assertEqual(names, {self.unrostered_auth_id: self.unrostered_username})
