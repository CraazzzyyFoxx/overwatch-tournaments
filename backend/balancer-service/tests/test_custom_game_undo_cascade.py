"""Undoing a match must delete its sides, not orphan them.

``CustomGameService.undo_last_match`` loads the match with both scored sides and
their frozen seats (``CasualMatchRepository.get_for_game`` eager-loads them to
roll the ranks back), then deletes it. ``CasualTeam.match_id`` is NOT NULL, and
``CasualMatch.teams`` shipped with ``passive_deletes=True`` alone -- which only
covers the collection being *unloaded*. For the loaded one the default cascade
de-associates instead: ``UPDATE casual.team SET match_id = NULL``, a
NotNullViolationError, so no host could ever take back a played match
(Sentry OWT-TOURNAMENTS-2BH).

Run against a real (SQLite) engine: the defect was in what the flush EMITS,
which only a flush can show. Sync ``Session`` because ``AsyncSession.delete`` /
``.flush`` are thin wrappers over exactly this unit of work and the suite has no
async SQLite driver.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.pool import StaticPool

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.models.casual import (  # noqa: E402
    CasualMatch,
    CasualMatchBusyPlayer,
    CasualPlayer,
    CasualTeam,
)
from shared.testing import install_postgres_type_shims  # noqa: E402

install_postgres_type_shims()

MATCH_ID = 501
CUSTOM_GAME_ID = 11


class UndoLastMatchCascadeTests(TestCase):
    def setUp(self) -> None:
        # Only the casual tables. SQLite does not validate a foreign key's target
        # at CREATE time and enforcement is off by default, so neither the rest of
        # the schema they reference nor the DB-side cascade needs to exist here --
        # which is the point: whatever disappears, the ORM did.
        tables = [CasualMatch.__table__, CasualTeam.__table__, CasualPlayer.__table__]
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)

        self.statements: list[str] = []

        @sa.event.listens_for(self.engine, "before_cursor_execute")
        def _record(_conn, _cursor, statement, _params, _context, _executemany):  # noqa: ANN001, ANN202
            self.statements.append(" ".join(statement.split()))

        self.session = Session(self.engine)
        self.addCleanup(self.session.close)

        self.session.execute(
            sa.insert(CasualMatch.__table__).values(
                id=MATCH_ID, custom_game_id=CUSTOM_GAME_ID, lobby_index=0, points_per_win_applied=25
            )
        )
        for team_id, side, score in ((147, "home", 2), (148, "away", 1)):
            self.session.execute(
                sa.insert(CasualTeam.__table__).values(
                    id=team_id, match_id=MATCH_ID, side=side, name=side.title(), score=score
                )
            )
            self.session.execute(
                sa.insert(CasualPlayer.__table__).values(
                    id=team_id,
                    team_id=team_id,
                    workspace_member_id=team_id,
                    display_name_snapshot="Alpha",
                    role=None,
                    rank=2500,
                )
            )
        self.session.commit()
        self.statements.clear()

    def _undo(self) -> None:
        """The two statements ``undo_last_match`` ends on: the eager-loaded read
        ``CasualMatchRepository.get_for_game`` does, then the delete."""
        match = self.session.scalar(
            sa.select(CasualMatch)
            .where(CasualMatch.custom_game_id == CUSTOM_GAME_ID, CasualMatch.id == MATCH_ID)
            .options(selectinload(CasualMatch.teams).selectinload(CasualTeam.players))
        )
        assert match is not None
        self.assertEqual(2, len(match.teams))
        self.statements.clear()
        self.session.delete(match)
        self.session.flush()

    def test_undo_never_de_associates_a_side(self) -> None:
        self._undo()

        self.assertEqual(
            [],
            [s for s in self.statements if s.startswith("UPDATE casual.team")],
            msg="the default cascade nulls CasualTeam.match_id, which is NOT NULL",
        )

    def test_undo_leaves_no_orphan_sides_or_seats(self) -> None:
        self._undo()

        for table in (CasualTeam.__table__, CasualPlayer.__table__):
            with self.subTest(table=table.fullname):
                self.assertEqual(
                    0,
                    self.session.scalar(sa.select(sa.func.count()).select_from(table)),
                    msg=f"{table.fullname} rows outlived the match that owned them",
                )

    def test_the_database_cascade_it_relies_on_exists(self) -> None:
        """``passive_deletes`` is only safe while the DB cleans up what was never
        loaded -- for both sides, their seats, and the other-lobby snapshot."""
        for model, column in (
            (CasualTeam, "match_id"),
            (CasualPlayer, "team_id"),
            (CasualMatchBusyPlayer, "match_id"),
        ):
            with self.subTest(model=model.__name__):
                owner = model.__table__.c[column]
                self.assertFalse(owner.nullable)
                self.assertEqual(["CASCADE"], [fk.ondelete for fk in owner.foreign_keys])
