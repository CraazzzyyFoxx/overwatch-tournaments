"""A scrim result must not enqueue a tournament recalculation or an achievement run.

Design: ``docs/plans/2026-08-12-scrim-rooms.md`` §5.

Both captains submitting agreeing reports runs
``services/encounter/captain.py:_recompute_encounter_result``, which fires
``enqueue_tournament_recalculation`` and ``_enqueue_encounter_completed`` at the
scrim's *container* tournament. §4.1 gives that container no standings, no
bracket, no stage items and no rosters, so the design assumed both fan-outs would
be inert. For the recalculation that assumption is **false**, and
``ScrimStandingsInventionTests`` below reproduces exactly why: the elimination
branch of the standings builder derives its participants from encounters when
seeds are absent, so it manufactures a "1st place" row for two rosterless teams
— for every room in the workspace, on every report.

The guards live at the enqueue sites, keyed on "is this tournament a scrim
container" (``shared/services/scrim_scope.py``). ``is_hidden`` is deliberately
NOT the predicate: hidden *preview* tournaments are real tournaments that do want
standings and brackets, and
``test_hidden_preview_tournament_still_enqueues_a_standings_job`` fails if anyone
widens it that way.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


models = importlib.import_module("shared.models")
enums = importlib.import_module("shared.core.enums")
standings_service = importlib.import_module("src.services.standings.service")
tournament_events = importlib.import_module("src.services.tournament.events")
captain = importlib.import_module("src.services.encounter.captain")
scrim_scope = importlib.import_module("shared.services.scrim_scope")
ScrimRoom = importlib.import_module("shared.models.tournament.scrim").ScrimRoom
create_sqlite_tables = importlib.import_module("shared.testing").create_sqlite_tables


# Only Postgres-only column types need help; rendering them as JSON keeps the
# DDL SQLite-compatible without altering any column these paths read. ARRAY
# columns on Stage already use a JSON variant under SQLite.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


# SQLite only auto-populates an ``INTEGER PRIMARY KEY`` (a rowid alias). The
# models' ids are ``BigInteger``, which renders as ``BIGINT`` and is left NULL,
# so the ORM's standings INSERT would fail for a reason that has nothing to do
# with what these tests measure.
@compiles(sa.BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "INTEGER"


# The tables reachable from ``recalculate_for_tournament`` and from the scrim
# predicate. Foreign keys leaving this set (``workspace``, ``players.user``,
# ``catalog.entity``, ``auth.user``) are unenforced under SQLite, so those tables
# are deliberately not created.
TABLE_NAMES = (
    "tournament.tournament",
    "tournament.stage",
    "tournament.stage_round_best_of",
    "tournament.stage_item",
    "tournament.stage_item_input",
    "tournament.team",
    "tournament.player",
    "encounter.encounter",
    "encounter.team",
    # The native has_logs EXISTS reaches both the observed match and its game.
    "stats.match",
    "encounter.game",
    # The stage read finds third-place matches through their bracket links.
    "tournament.encounter_link",
    "tournament.standing",
    "tournament.standing_pin",
    "tournament.scrim_room",
)

WORKSPACE_ID = 1
REAL_TOURNAMENT_ID = 1
PREVIEW_TOURNAMENT_ID = 2
CONTAINER_ID = 3


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``.

    These paths await ``execute`` / ``scalar`` / ``flush`` / ``commit`` and
    nothing else, and no async SQLite driver is installed, so a sync session
    behind async methods runs the genuine statements without aiosqlite.
    """

    def __init__(self, session: Session) -> None:
        self.sync_session = session

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.execute(statement, *args, **kwargs)

    async def scalar(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.scalar(statement, *args, **kwargs)

    async def scalars(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.scalars(statement, *args, **kwargs)

    async def flush(self) -> None:
        self.sync_session.flush()

    async def commit(self) -> None:
        self.sync_session.commit()

    def add(self, obj) -> None:  # noqa: ANN001
        self.sync_session.add(obj)

    def add_all(self, objs) -> None:  # noqa: ANN001
        self.sync_session.add_all(objs)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        return getattr(self.sync_session, name)


class _Fixture:
    """A throwaway in-memory database plus row builders for it."""

    def __init__(self) -> None:
        metadata = models.Tournament.__table__.metadata
        tables = [metadata.tables[name] for name in TABLE_NAMES]
        # StaticPool pins one connection: ``:memory:`` databases (including the
        # ATTACHed ones standing in for Postgres schemas) live and die with it.
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema} | {"encounter"}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            # Hand-written: ``encounter.scoring_rule``'s server default is
            # ``'[]'::jsonb`` and its CHECK calls ``jsonb_typeof``, neither of
            # which sqlite can parse. The standings read it through
            # ``Stage.scoring_rule``, so the table has to exist -- its
            # constraints are Postgres's job, not this fixture's.
            conn.exec_driver_sql(
                "CREATE TABLE encounter.scoring_rule ("
                " id INTEGER PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,"
                " workspace_id INTEGER NOT NULL, preset VARCHAR(16) NOT NULL,"
                " columns JSON NOT NULL, placement_points JSON NOT NULL,"
                " game_formula VARCHAR(500) NOT NULL, end_formula VARCHAR(500) NOT NULL)"
            )
            # Same reason: its FKs use Postgres's ``SET NULL (stage_id)`` form.
            conn.exec_driver_sql(
                "CREATE TABLE tournament.bracket_encounter ("
                " encounter_id INTEGER PRIMARY KEY, tournament_id INTEGER NOT NULL,"
                " stage_id INTEGER, stage_item_id INTEGER, round INTEGER NOT NULL)"
            )
            # Stage.node loads with the stage; no scrim stage has one, so the table only has to exist (JSONB has no sqlite form).
            conn.exec_driver_sql(
                "CREATE TABLE tournament.flow_node ("
                " id INTEGER PRIMARY KEY, tournament_id INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,"
                " status TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}', stage_id INTEGER,"
                " position_x REAL NOT NULL DEFAULT 0, position_y REAL NOT NULL DEFAULT 0,"
                " started_at TIMESTAMP, completed_at TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP)"
            )
            create_sqlite_tables(conn, tables)
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)
        self._next_id = 1000

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def insert(self, table, **values) -> None:  # noqa: ANN001, ANN003
        self.session.execute(sa.insert(table).values(**values))

    def tournament(self, tournament_id: int, *, name: str, is_hidden: bool, dated: bool = True) -> int:
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=WORKSPACE_ID,
            name=name,
            slug=f"tournament-{tournament_id}",
            is_hidden=is_hidden,
            # A lazily provisioned scrim container never gets a start date; a real
            # tournament always has one.
            start_date=datetime(2026, 1, 1, tzinfo=UTC) if dated else None,
        )
        return tournament_id

    def bracket_stage(self, tournament_id: int, *, name: str, order: int) -> int:
        """A stage exactly as ``create_room`` provisions one: SINGLE_ELIMINATION,
        ``max_rounds=1``, and no ``StageItem`` rows at all."""
        stage_id = self._id()
        self.insert(
            models.Stage.__table__,
            id=stage_id,
            tournament_id=tournament_id,
            # NOT NULL since the encounter layer landed; the room's rule row is
            # not created here because its PG-only CHECKs have no sqlite form.
            scoring_rule_id=stage_id,
            name=name,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            order=order,
            max_rounds=1,
        )
        return stage_id

    def team(self, tournament_id: int, name: str) -> int:
        team_id = self._id()
        self.insert(
            models.Team.__table__,
            id=team_id,
            tournament_id=tournament_id,
            name=name,
            balancer_name=name,
        )
        return team_id

    def completed_encounter(self, tournament_id: int, *, stage_id: int | None, label: str) -> dict[str, int]:
        home = self.team(tournament_id, f"{label} home")
        away = self.team(tournament_id, f"{label} away")
        encounter_id = self._id()
        self.insert(
            sa.table(
                "scoring_rule",
                sa.column("id"),
                sa.column("workspace_id"),
                sa.column("preset"),
                sa.column("columns"),
                sa.column("placement_points"),
                sa.column("game_formula"),
                sa.column("end_formula"),
                schema="encounter",
            ),
            id=stage_id,
            workspace_id=WORKSPACE_ID,
            preset="wins",
            columns="[]",
            placement_points="[]",
            game_formula="win",
            end_formula="games >= best_of or max_wins * 2 > best_of",
        )
        self.insert(
            models.Encounter.__table__,
            id=encounter_id,
            workspace_id=WORKSPACE_ID,
            discipline="overwatch",
            tournament_id=tournament_id,
            scoring_rule_id=stage_id,
            name=label,
            slot_count=2,
            best_of=3,
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
            result_source="admin",
            result_version=1,
        )
        if stage_id is not None:
            self.insert(
                sa.table(
                    "bracket_encounter",
                    sa.column("encounter_id"),
                    sa.column("tournament_id"),
                    sa.column("stage_id"),
                    sa.column("round"),
                    schema="tournament",
                ),
                encounter_id=encounter_id,
                tournament_id=tournament_id,
                stage_id=stage_id,
                round=1,
            )
        # The result is a PLACE on each participation now (D53, D60).
        for slot, (team_id, score, placement) in enumerate(((home, 2.0, 1), (away, 1.0, 2)), 1):
            self.insert(
                models.EncounterTeam.__table__,
                id=encounter_id * 10 + slot,
                encounter_id=encounter_id,
                tournament_id=tournament_id,
                slot=slot,
                team_id=team_id,
                name=f"team{team_id}",
                active=True,
                score=score,
                placement=placement,
            )
        return {"home": home, "away": away, "encounter": encounter_id}

    def room(self, *, index: int) -> dict[str, int]:
        """One scrim room: stage + two rosterless teams + encounter + ScrimRoom."""
        stage_id = self.bracket_stage(CONTAINER_ID, name=f"room {index}", order=index)
        parts = self.completed_encounter(CONTAINER_ID, stage_id=stage_id, label=f"room {index}")
        self.insert(
            ScrimRoom.__table__,
            id=self._id(),
            token=f"token{index}",
            label=f"room {index}",
            workspace_id=WORKSPACE_ID,
            tournament_id=CONTAINER_ID,
            stage_id=stage_id,
            encounter_id=parts["encounter"],
            created_by_auth_user_id=1,
        )
        parts["stage"] = stage_id
        return parts


class _DatabaseTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = _Fixture()

    def tearDown(self) -> None:
        self.db.close()


class ScrimContainerPredicateTests(_DatabaseTestCase):
    """The predicate itself: container yes, everything else no."""

    async def test_container_is_recognised_and_ordinary_tournaments_are_not(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False)
        self.db.tournament(PREVIEW_TOURNAMENT_ID, name="Preview", is_hidden=True)
        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True)
        self.db.room(index=1)
        self.db.session.commit()

        self.assertTrue(await scrim_scope.is_scrim_container(self.db.shim, CONTAINER_ID))
        self.assertFalse(await scrim_scope.is_scrim_container(self.db.shim, REAL_TOURNAMENT_ID))
        # The distinction that ``is_hidden`` would erase.
        self.assertFalse(await scrim_scope.is_scrim_container(self.db.shim, PREVIEW_TOURNAMENT_ID))
        self.assertFalse(await scrim_scope.is_scrim_container(self.db.shim, None))


class RecalculationEnqueueTests(_DatabaseTestCase):
    """``enqueue_tournament_recalculation`` must skip the container only."""

    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False)
        self.db.tournament(PREVIEW_TOURNAMENT_ID, name="Preview", is_hidden=True)
        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True)
        self.db.room(index=1)
        self.db.session.commit()

    async def _enqueue(self, tournament_id: int) -> AsyncMock:
        request = AsyncMock()
        with (
            patch.object(tournament_events.jobs_service, "request_standings_recalculation", request),
            patch.object(tournament_events, "emit", AsyncMock()),
        ):
            await tournament_events.enqueue_tournament_recalculation(self.db.shim, tournament_id)
        return request

    async def test_scrim_result_does_not_enqueue_a_standings_job(self) -> None:
        request = await self._enqueue(CONTAINER_ID)
        request.assert_not_awaited()

    async def test_real_tournament_still_enqueues_a_standings_job(self) -> None:
        request = await self._enqueue(REAL_TOURNAMENT_ID)
        request.assert_awaited_once_with(self.db.shim, REAL_TOURNAMENT_ID)

    async def test_hidden_preview_tournament_still_enqueues_a_standings_job(self) -> None:
        """The predicate must not be widened to ``Tournament.is_hidden``.

        A preview tournament is a real tournament that has not been published
        yet; its organizer is watching its standings and bracket fill in. Keying
        the skip on ``is_hidden`` would silently freeze both.
        """
        request = await self._enqueue(PREVIEW_TOURNAMENT_ID)
        request.assert_awaited_once_with(self.db.shim, PREVIEW_TOURNAMENT_ID)

    async def test_one_transaction_requests_the_standings_once(self) -> None:
        """A completing result asks twice (settlement + caller); one job answers both, the next commit asks again."""
        request = AsyncMock()
        with (
            patch.object(tournament_events.jobs_service, "request_standings_recalculation", request),
            patch.object(tournament_events, "emit", AsyncMock()),
        ):
            for _ in range(2):
                await tournament_events.enqueue_tournament_recalculation(self.db.shim, REAL_TOURNAMENT_ID)
            request.assert_awaited_once()
            await self.db.shim.commit()
            await tournament_events.enqueue_tournament_recalculation(self.db.shim, REAL_TOURNAMENT_ID)
        self.assertEqual(2, request.await_count)


class ScrimStandingsInventionTests(_DatabaseTestCase):
    """Why the enqueue guard is load-bearing, reproduced.

    The design expected an empty container to be inert on this path. It is not.
    This test hands ``recalculate_for_tournament`` the container directly — i.e.
    what the standings worker would do if a job for it were ever created — and
    pins both halves of the damage: invented standings, and O(rooms) work per
    result. If a future change makes the worker itself refuse an empty
    tournament, this test is the one that should be revisited, not deleted:
    it also documents that a stage with no seeds legitimately derives its
    participants from encounters, which is what real bracket-only tournaments
    depend on.
    """

    async def test_recalculating_a_container_invents_standings_for_every_room(self) -> None:
        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True, dated=False)
        rooms = [self.db.room(index=index) for index in (1, 2, 3)]
        self.db.session.commit()

        self.assertEqual(
            0,
            self.db.session.scalar(sa.select(sa.func.count()).select_from(models.Standing.__table__)),
        )

        run = await standings_service.standings_service.recalculate_for_tournament(
            self.db.shim, CONTAINER_ID, commit=True
        )

        rows = self.db.session.execute(
            sa.select(
                models.Standing.__table__.c.stage_id,
                models.Standing.__table__.c.team_id,
                models.Standing.__table__.c.overall_position,
            ).order_by(models.Standing.__table__.c.stage_id, models.Standing.__table__.c.position)
        ).all()

        # Two rows per room, and the home team of EVERY room is "1st".
        self.assertEqual(2 * len(rooms), len(rows))
        self.assertEqual(
            [(room["stage"], room["home"], 1) for room in rooms],
            [tuple(row) for row in rows if row.overall_position == 1],
        )
        # One room finishing rewrote the standings of all three.
        self.assertEqual(
            {room["stage"] for room in rooms},
            {row.stage_id for row in rows},
        )
        # And every room's stage counts as a concluded bracket.
        self.assertEqual({room["stage"] for room in rooms}, set(run.completed_stage_ids))
