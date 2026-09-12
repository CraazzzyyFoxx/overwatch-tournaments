"""Integration tests for the "My ranks" shortcut in ``workspace_roster``.

Covers both ``roster_page(author_only=True)`` and ``roster_summary`` -- the
two chip-count/list surfaces the add-players dialog reads.

Requires a reachable database via POSTGRES_* env vars (use a disposable DB such
as anak_dev -- NEVER production). Skips cleanly if the DB is unreachable.

Both are SQL ``EXISTS``/aggregate queries, not something a mocked-session unit
test can exercise honestly -- this proves them against a real engine instead.
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
from shared.services import workspace_roster  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402

_UNIQUE = 0


def _uniq() -> int:
    global _UNIQUE
    _UNIQUE += 1
    return _UNIQUE


class RosterPageAuthorOnlyTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        # psycopg async cannot run on the Proactor loop (Windows default).
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        suffix = f"roster-author-only-{os.getpid()}-{_uniq()}"

        async with self.Session() as session:
            workspace = Workspace(slug=f"ws-{suffix}", name=f"WS {suffix}")
            session.add(workspace)
            await session.flush()

            host = AuthUser(username=f"host-{suffix}", email=f"host-{suffix}@example.test")
            other_host = AuthUser(username=f"other-{suffix}", email=f"other-{suffix}@example.test")
            session.add_all([host, other_host])
            await session.flush()

            # One member ranked by the acting host, one ranked by a different
            # host, one ranked by nobody: the filter must select exactly the first.
            mine = User(name=f"mine-{suffix}")
            theirs = User(name=f"theirs-{suffix}")
            unranked = User(name=f"unranked-{suffix}")
            session.add_all([mine, theirs, unranked])
            await session.flush()

            mine_member = WorkspaceMember(workspace_id=workspace.id, player_id=mine.id)
            theirs_member = WorkspaceMember(workspace_id=workspace.id, player_id=theirs.id)
            unranked_member = WorkspaceMember(workspace_id=workspace.id, player_id=unranked.id)
            session.add_all([mine_member, theirs_member, unranked_member])
            await session.flush()

            session.add_all(
                [
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=mine_member.id,
                        author_user_id=host.id,
                        role="tank",
                        rank_value=2500,
                    ),
                    MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=theirs_member.id,
                        author_user_id=other_host.id,
                        role="tank",
                        rank_value=2500,
                    ),
                ]
            )
            await session.commit()

            self.workspace_id = workspace.id
            self.host_id = host.id
            self.other_host_id = other_host.id
            self.player_ids = [mine.id, theirs.id, unranked.id]
            self.mine_member_id = mine_member.id

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as session:
            await session.execute(sa.delete(MemberRank).where(MemberRank.workspace_id == self.workspace_id))
            await session.execute(sa.delete(WorkspaceMember).where(WorkspaceMember.workspace_id == self.workspace_id))
            await session.execute(sa.delete(User).where(User.id.in_(self.player_ids)))
            await session.execute(sa.delete(AuthUser).where(AuthUser.id.in_([self.host_id, self.other_host_id])))
            await session.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await session.commit()
        await self.engine.dispose()

    async def test_author_only_narrows_to_that_authors_ranked_members(self) -> None:
        async with self.Session() as session:
            rows, total = await workspace_roster.roster_page(
                session,
                workspace_id=self.workspace_id,
                author_user_id=self.host_id,
                author_only=True,
            )
        self.assertEqual(total, 1)
        self.assertEqual([row.member_id for row in rows], [self.mine_member_id])

    async def test_author_only_is_scoped_per_author(self) -> None:
        async with self.Session() as session:
            rows, total = await workspace_roster.roster_page(
                session,
                workspace_id=self.workspace_id,
                author_user_id=self.other_host_id,
                author_only=True,
            )
        self.assertEqual(total, 1)
        self.assertNotEqual(rows[0].member_id, self.mine_member_id)

    async def test_author_only_false_returns_everyone(self) -> None:
        async with self.Session() as session:
            _rows, total = await workspace_roster.roster_page(
                session,
                workspace_id=self.workspace_id,
                author_user_id=self.host_id,
                author_only=False,
            )
        self.assertEqual(total, 3)

    async def test_summary_reports_workspace_total_and_this_authors_count(self) -> None:
        async with self.Session() as session:
            total, author_total = await workspace_roster.roster_summary(
                session, workspace_id=self.workspace_id, author_user_id=self.host_id
            )
        self.assertEqual(total, 3)
        self.assertEqual(author_total, 1)

    async def test_summary_author_total_is_scoped_per_author(self) -> None:
        async with self.Session() as session:
            total, author_total = await workspace_roster.roster_summary(
                session, workspace_id=self.workspace_id, author_user_id=self.other_host_id
            )
        self.assertEqual(total, 3)
        self.assertEqual(author_total, 1)

    async def test_summary_without_an_author_skips_the_authored_count(self) -> None:
        async with self.Session() as session:
            total, author_total = await workspace_roster.roster_summary(
                session, workspace_id=self.workspace_id, author_user_id=None
            )
        self.assertEqual(total, 3)
        self.assertEqual(author_total, 0)
