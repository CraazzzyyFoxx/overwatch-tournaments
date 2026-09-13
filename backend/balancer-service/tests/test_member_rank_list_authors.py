"""Integration test for ``MemberRankService.list_authors``.

The add-players dialog's per-author filter chips beyond "Everyone"/"My
ranks" -- who else has personally rank-corrected someone in this workspace,
and how many. Requires a reachable database via POSTGRES_* env vars (use a
disposable DB such as anak_dev -- NEVER production). Skips cleanly if the
DB is unreachable.

A ``group by``/``count distinct`` aggregate, not something a mocked-session
unit test can exercise honestly -- this proves it against a real engine
instead, mirroring ``test_workspace_roster_author_only.py``.
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
from shared.models.member_rank.member_rank import MemberRank  # noqa: E402
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.services.member_rank import member_rank_service  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402

_UNIQUE = 0


def _uniq() -> int:
    global _UNIQUE
    _UNIQUE += 1
    return _UNIQUE


class MemberRankListAuthorsTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        # psycopg async cannot run on the Proactor loop (Windows default).
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        suffix = f"member-rank-authors-{os.getpid()}-{_uniq()}"

        async with self.Session() as session:
            workspace = Workspace(slug=f"ws-{suffix}", name=f"WS {suffix}")
            session.add(workspace)
            await session.flush()

            busy_host = AuthUser(username=f"busy-{suffix}", email=f"busy-{suffix}@example.test")
            quiet_host = AuthUser(username=f"quiet-{suffix}", email=f"quiet-{suffix}@example.test")
            session.add_all([busy_host, quiet_host])
            await session.flush()

            first = User(name=f"first-{suffix}")
            second = User(name=f"second-{suffix}")
            unranked = User(name=f"unranked-{suffix}")
            session.add_all([first, second, unranked])
            await session.flush()

            first_member = WorkspaceMember(workspace_id=workspace.id, player_id=first.id)
            second_member = WorkspaceMember(workspace_id=workspace.id, player_id=second.id)
            unranked_member = WorkspaceMember(workspace_id=workspace.id, player_id=unranked.id)
            session.add_all([first_member, second_member, unranked_member])
            await session.flush()

            session.add_all(
                [
                    # busy_host ranked two different members, on two roles each --
                    # the count must be distinct members, not distinct rows.
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=first_member.id,
                        author_user_id=busy_host.id,
                        role="tank",
                        rank_value=2500,
                    ),
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=first_member.id,
                        author_user_id=busy_host.id,
                        role="dps",
                        rank_value=2400,
                    ),
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=second_member.id,
                        author_user_id=busy_host.id,
                        role="tank",
                        rank_value=2500,
                    ),
                    # quiet_host ranked exactly one member.
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=second_member.id,
                        author_user_id=quiet_host.id,
                        role="support",
                        rank_value=2300,
                    ),
                    # The workspace canon (no author) must never appear as an author.
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=unranked_member.id,
                        author_user_id=None,
                        role="tank",
                        rank_value=2500,
                    ),
                ]
            )
            await session.commit()

            self.workspace_id = workspace.id
            self.busy_host_id = busy_host.id
            self.quiet_host_id = quiet_host.id
            self.player_ids = [first.id, second.id, unranked.id]

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as session:
            await session.execute(sa.delete(MemberRank).where(MemberRank.workspace_id == self.workspace_id))
            await session.execute(sa.delete(WorkspaceMember).where(WorkspaceMember.workspace_id == self.workspace_id))
            await session.execute(sa.delete(User).where(User.id.in_(self.player_ids)))
            await session.execute(sa.delete(AuthUser).where(AuthUser.id.in_([self.busy_host_id, self.quiet_host_id])))
            await session.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await session.commit()
        await self.engine.dispose()

    async def test_lists_every_author_with_a_distinct_member_count_busiest_first(self) -> None:
        async with self.Session() as session:
            authors = await member_rank_service.list_authors(session, workspace_id=self.workspace_id)
        self.assertEqual(authors, [(self.busy_host_id, 2), (self.quiet_host_id, 1)])

    async def test_excludes_the_workspace_canon(self) -> None:
        async with self.Session() as session:
            authors = await member_rank_service.list_authors(session, workspace_id=self.workspace_id)
        self.assertNotIn(None, [author_user_id for author_user_id, _ in authors])

    async def test_scoped_to_the_workspace(self) -> None:
        async with self.Session() as session:
            authors = await member_rank_service.list_authors(session, workspace_id=self.workspace_id + 999999)
        self.assertEqual(authors, [])
