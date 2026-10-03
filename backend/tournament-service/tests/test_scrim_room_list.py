"""Execution tests for ``scrim/service.py:list_rooms_for_viewer``.

This read had no coverage at all, which is how it shipped with a ``DISTINCT``
alongside an ``ORDER BY (closed_at IS NULL)`` — a combination Postgres rejects
outright (``InvalidColumnReferenceError``: for SELECT DISTINCT, ORDER BY
expressions must appear in select list), so the scrims page 500'd on its first
load in production.

Two layers, because neither alone would have caught it:

* the query is RUN, against a real (SQLite) database, so its joins, filters and
  ordering are exercised rather than merely compiled;
* the emitted SQL is asserted to carry no ``DISTINCT``, because SQLite happily
  accepts the combination Postgres refuses. Execution here proves the shape;
  that assertion is what defends the dialect rule.
"""

from __future__ import annotations

import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # noqa: E402

from src import models  # noqa: E402
from src.services.scrim import service as scrim  # noqa: E402


# Postgres-only column types appear on tables reachable from these models; make
# the DDL SQLite-compatible without touching any column this read looks at.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


# SQLite has no BIGSERIAL: BigInteger primary keys do not autoincrement, which
# matters because rows here are inserted with explicit ids anyway.
@compiles(sa.BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "INTEGER"


# Only what this read touches. FKs leaving the set (``workspace``, ``auth.user``,
# ``tournament.stage``) go unenforced under SQLite, so those tables are omitted.
# ``tournament.player`` carries no rows here but must exist: ``Team.avg_sr`` and
# ``Team.total_sr`` are ``column_property`` aggregates over it, so every SELECT of
# a team emits a correlated subquery against it.
TABLE_NAMES = (
    "players.user",
    "tournament.tournament",
    "tournament.team",
    "tournament.player",
    "tournament.encounter",
    # ``Encounter.has_logs`` is the same kind of ``column_property`` EXISTS,
    # over this table (see ``shared/models/matches/match.py``) — carries no
    # rows here but must exist for the same reason as ``tournament.player``
    # above.
    "matches.match",
    "tournament.scrim_room",
)

WORKSPACE_ID = 1
CONTAINER_ID = 7

# auth ids
ME = 100
OPPONENT = 200
STRANGER = 300
# players.user ids
MY_PLAYER = 1100
OPPONENT_PLAYER = 1200


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``.

    ``list_rooms_for_viewer`` awaits only ``execute``/``scalar``, and no async
    SQLite driver is installed, so a sync session behind async methods runs the
    genuine statements without aiosqlite. Same shim as
    ``test_scrim_recalculation_exclusion.py``.
    """

    def __init__(self, session: Session) -> None:
        self.sync_session = session
        self.statements: list[Any] = []

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        self.statements.append(statement)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.execute(statement, *args, **kwargs)

    async def scalar(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.scalar(statement, *args, **kwargs)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        return getattr(self.sync_session, name)


def _user(auth_id: int, *, workspaces: list[int] | None = None, staff_of: list[int] | None = None) -> Any:
    """``staff_of`` names the workspaces where this user holds ``match.result``."""
    staff = list(staff_of or [])
    return SimpleNamespace(
        id=auth_id,
        is_superuser=False,
        get_workspace_ids=lambda: list(workspaces if workspaces is not None else [WORKSPACE_ID]),
        has_workspace_permission=lambda workspace_id, resource, action: workspace_id in staff,
    )


class _Fixture:
    def __init__(self) -> None:
        metadata = models.Tournament.__table__.metadata
        tables = [metadata.tables[name] for name in TABLE_NAMES]
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)
        self._next_id = 500

        self.insert(models.User.__table__, id=MY_PLAYER, name="me", auth_user_id=ME)
        self.insert(models.User.__table__, id=OPPONENT_PLAYER, name="opponent", auth_user_id=OPPONENT)
        self.insert(
            models.Tournament.__table__,
            id=CONTAINER_ID,
            workspace_id=WORKSPACE_ID,
            name=scrim.CONTAINER_NAME,
            slug="scrims",
            is_hidden=True,
            is_league=False,
            start_date=datetime(2026, 8, 12, tzinfo=UTC),
            end_date=datetime(2026, 8, 12, tzinfo=UTC),
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def insert(self, table, **values) -> None:  # noqa: ANN001, ANN003
        self.session.execute(sa.insert(table).values(**values))

    def room(
        self,
        room_id: int,
        *,
        created_by: int,
        home_captain: int | None,
        away_captain: int | None,
        closed: bool = False,
    ) -> int:
        """One room exactly as ``create_room`` provisions it."""
        teams = []
        for captain in (home_captain, away_captain):
            team_id = self._id()
            self.insert(
                models.Team.__table__,
                id=team_id,
                tournament_id=CONTAINER_ID,
                name=f"team{team_id}",
                balancer_name=f"team{team_id}",
                captain_id=captain,
            )
            teams.append(team_id)
        encounter_id = self._id()
        self.insert(
            models.Encounter.__table__,
            id=encounter_id,
            tournament_id=CONTAINER_ID,
            name=f"room{room_id}",
            home_team_id=teams[0],
            away_team_id=teams[1],
            home_score=0,
            away_score=0,
            round=1,
            best_of=3,
            status="OPEN",
        )
        self.insert(
            models.ScrimRoom.__table__ if hasattr(models, "ScrimRoom") else _scrim_table(),
            id=room_id,
            token=f"tok{room_id}",
            label=f"room{room_id}",
            workspace_id=WORKSPACE_ID,
            tournament_id=CONTAINER_ID,
            stage_id=self._id(),
            encounter_id=encounter_id,
            created_by_auth_user_id=created_by,
            closed_at=datetime(2026, 8, 12, tzinfo=UTC) if closed else None,
        )
        return room_id


def _scrim_table():  # noqa: ANN202
    from shared.models.tournament.scrim import ScrimRoom

    return ScrimRoom.__table__


class _ListCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = _Fixture()
        self.addCleanup(self.db.close)

    async def rooms_for(self, user: Any, *, scope: str = "mine") -> list[dict]:
        self.db.session.commit()
        return await scrim.scrim_service.list_rooms_for_viewer(self.db.shim, user, WORKSPACE_ID, scope=scope)


class TheListRuns(_ListCase):
    """The regression itself: this read must execute, not raise."""

    async def test_a_creator_sees_their_own_room(self) -> None:
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None)
        rooms = await self.rooms_for(_user(ME))
        self.assertEqual([1], [room["id"] for room in rooms])
        self.assertEqual("home", rooms[0]["viewer_side"])

    async def test_a_captain_who_did_not_create_it_sees_it(self) -> None:
        """The opponent claimed the away side; the room is theirs to find again."""
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=OPPONENT_PLAYER)
        rooms = await self.rooms_for(_user(OPPONENT))
        self.assertEqual([1], [room["id"] for room in rooms])
        self.assertEqual("away", rooms[0]["viewer_side"])

    async def test_someone_elses_room_is_not_listed(self) -> None:
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=OPPONENT_PLAYER)
        self.assertEqual([], await self.rooms_for(_user(STRANGER)))

    async def test_a_non_member_is_refused_before_the_query_runs(self) -> None:
        from shared.core.errors import BaseAPIException as HTTPException

        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.rooms_for(_user(ME, workspaces=[42]))
        self.assertEqual(403, ctx.exception.status_code)


class TheListIsOrderedAndNotDeduplicated(_ListCase):
    async def test_open_rooms_come_first_then_newest_closed(self) -> None:
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None, closed=True)
        self.db.room(2, created_by=ME, home_captain=MY_PLAYER, away_captain=None, closed=True)
        self.db.room(3, created_by=ME, home_captain=MY_PLAYER, away_captain=None)
        rooms = await self.rooms_for(_user(ME))
        # 3 is open; 2 and 1 are history, newest first.
        self.assertEqual([3, 2, 1], [room["id"] for room in rooms])

    async def test_a_room_the_viewer_both_created_and_captains_appears_once(self) -> None:
        """Why no ``DISTINCT`` is needed: the OR matches on two of its branches
        at once, but every join is to a primary key, so there is still one row."""
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=MY_PLAYER)
        rooms = await self.rooms_for(_user(ME))
        self.assertEqual([1], [room["id"] for room in rooms])

    async def test_the_statement_carries_no_distinct(self) -> None:
        """SQLite accepts ``DISTINCT`` beside an ``ORDER BY`` expression that is
        not in the select list; Postgres raises ``InvalidColumnReferenceError``.
        Execution above therefore cannot defend this -- only the SQL can."""
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None)
        await self.rooms_for(_user(ME))

        room_selects = [
            str(statement.compile(dialect=sa.dialects.postgresql.dialect())) for statement in self.db.shim.statements
        ]
        self.assertTrue(room_selects, "the read issued no statement through execute()")
        for sql in room_selects:
            self.assertNotIn("DISTINCT", sql.upper())
            # Pins that the ordering is the computed expression the rule is about,
            # so this test cannot pass by the ordering having quietly been dropped.
            self.assertIn("ORDER BY", sql.upper())
            self.assertIn("IS NULL DESC", sql.upper())


class TheWorkspaceScopeIsForStaff(_ListCase):
    """``scope="workspace"`` is how a referee finds a room nobody is left to
    close — so it must list rooms the caller is no part of, and only for staff."""

    async def test_staff_see_a_room_they_neither_created_nor_captain(self) -> None:
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=OPPONENT_PLAYER)
        staff = _user(STRANGER, staff_of=[WORKSPACE_ID])
        self.assertEqual([], await self.rooms_for(staff))
        rooms = await self.rooms_for(staff, scope="workspace")
        self.assertEqual([1], [room["id"] for room in rooms])
        self.assertIsNone(rooms[0]["viewer_side"])
        self.assertTrue(rooms[0]["can_close"])

    async def test_a_plain_member_is_refused_the_workspace_scope(self) -> None:
        from shared.core.errors import BaseAPIException as HTTPException

        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.rooms_for(_user(STRANGER), scope="workspace")
        self.assertEqual(403, ctx.exception.status_code)

    async def test_staff_of_another_workspace_are_refused(self) -> None:
        from shared.core.errors import BaseAPIException as HTTPException

        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.rooms_for(_user(STRANGER, staff_of=[WORKSPACE_ID + 1]), scope="workspace")
        self.assertEqual(403, ctx.exception.status_code)

    async def test_the_workspace_scope_keeps_the_open_first_ordering(self) -> None:
        self.db.room(1, created_by=ME, home_captain=MY_PLAYER, away_captain=None, closed=True)
        self.db.room(2, created_by=OPPONENT, home_captain=OPPONENT_PLAYER, away_captain=None, closed=True)
        self.db.room(3, created_by=OPPONENT, home_captain=OPPONENT_PLAYER, away_captain=None)
        rooms = await self.rooms_for(_user(STRANGER, staff_of=[WORKSPACE_ID]), scope="workspace")
        self.assertEqual([3, 2, 1], [room["id"] for room in rooms])

    async def test_an_unknown_scope_is_refused(self) -> None:
        from shared.core.errors import BaseAPIException as HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self.rooms_for(_user(ME), scope="everything")
        self.assertEqual(422, ctx.exception.status_code)
