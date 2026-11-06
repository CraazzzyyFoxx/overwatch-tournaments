"""``sync_player_ranks`` runs its real query against a real engine (SQLite).

The claims under test are properties of the emitted SQL and the in-place update:
only rows of the named formation node are touched, only rows whose rank actually
differs are counted, and a payload member with no materialized row is a no-op.
A mocked session could not falsify any of them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from shared.models.catalog.role import CatalogRole, RoleDimension  # noqa: E402
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament.player_role import PlayerRole  # noqa: E402
from shared.models.tournament.team import Player, Team  # noqa: E402
from shared.models.tournament.tournament import Tournament  # noqa: E402
from shared.testing import create_sqlite_tables, install_postgres_type_shims  # noqa: E402
from src.services.team_export import (  # noqa: E402
    MaterializationMember,
    MaterializationTeam,
    sync_player_ranks,
)

install_postgres_type_shims()

TABLES = (
    Workspace.__table__,
    WorkspaceMember.__table__,
    Tournament.__table__,
    Team.__table__,
    Player.__table__,
    RoleDimension.__table__,
    CatalogRole.__table__,
    PlayerRole.__table__,
)


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` (no aiosqlite installed)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def scalars(self, statement):  # noqa: ANN001, ANN202
        return self._session.scalars(statement)

    async def flush(self) -> None:
        self._session.flush()


def _team(name: str, *members: tuple[str, int | None]) -> MaterializationTeam:
    return MaterializationTeam(
        balancer_name=name,
        members=tuple(MaterializationMember(name=tag, rank=rank, slot_code="tank") for tag, rank in members),
    )


class SyncPlayerRanksTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in TABLES if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            create_sqlite_tables(conn, TABLES)
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)

        self.session.execute(sa.insert(Workspace.__table__).values(id=1, slug="ws", name="WS"))
        for tournament_id in (1, 2):
            self.session.execute(
                sa.insert(Tournament.__table__).values(
                    id=tournament_id,
                    workspace_id=1,
                    name=f"T{tournament_id}",
                    slug=f"t{tournament_id}",
                )
            )
            self.session.execute(
                sa.insert(Team.__table__).values(
                    id=tournament_id, tournament_id=tournament_id, name="Team", balancer_name="A#1"
                )
            )
        # (name, tournament, rank) — "A#1" is in both formation nodes on purpose.
        for player_id, (name, tournament_id, rank) in enumerate(
            [("A#1", 1, 1000), ("B#2", 1, 2000), ("A#1", 2, 500)], start=1
        ):
            self.session.execute(
                sa.insert(WorkspaceMember.__table__).values(id=player_id, workspace_id=1, player_id=player_id)
            )
            self.session.execute(
                sa.insert(Player.__table__).values(
                    id=player_id,
                    tournament_id=tournament_id,
                    formation_node_id=10 + tournament_id,
                    team_id=tournament_id,
                    workspace_member_id=player_id,
                    name=name,
                    rank=rank,
                    is_substitution=False,
                )
            )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _rank(self, player_id: int) -> int | None:
        return self.session.scalar(sa.select(Player.rank).where(Player.id == player_id))

    async def test_updates_only_changed_rows_of_this_formation_node(self) -> None:
        # B#2 already holds 2000, C#3 was never materialized, and the A#1 of
        # tournament 2 is a different roster row that must not move.
        updated = await sync_player_ranks(
            self.shim,
            11,
            [_team("A#1", ("A#1", 3000), ("B#2", 2000), ("C#3", 999))],
        )

        self.assertEqual(1, updated)
        self.session.expire_all()
        self.assertEqual(3000, self._rank(1))
        self.assertEqual(2000, self._rank(2))
        self.assertEqual(500, self._rank(3))

    async def test_empty_payload_touches_nothing(self) -> None:
        self.assertEqual(0, await sync_player_ranks(self.shim, 11, [_team("A#1")]))
        self.assertEqual(1000, self._rank(1))

    async def test_a_zero_rank_is_no_rank(self) -> None:
        """0 has no meaning: the materialization boundary stores it as NULL, never as a 0."""
        self.assertEqual(2, await sync_player_ranks(self.shim, 11, [_team("A#1", ("A#1", 0), ("B#2", None))]))
        self.session.expire_all()
        self.assertEqual((None, None), (self._rank(1), self._rank(2)))
