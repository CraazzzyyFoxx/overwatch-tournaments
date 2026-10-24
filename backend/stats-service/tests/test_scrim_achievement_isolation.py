"""A completed scrim must not award, remove, or crash on an achievement.

Design: ``docs/plans/2026-08-12-scrim-rooms.md`` §5.

When both captains agree on a scrim's result, tournament-service publishes an
``EncounterCompletedEvent`` and stats-service republishes it as an
``AchievementEvaluateEvent`` pointed at the scrim's *container* tournament
(``serve_worker.py``'s encounter-completed consumer), so ``runner.run_evaluation`` runs against a tournament
with two ``Team`` rows, no ``Player`` rows, no ``Standing`` rows, no stage items,
no ``division_grid_version_id`` and a NULL ``start_date``.

Unlike ``analytics/service.py:get_matches_for_tournaments`` — where the same "it will be inert"
expectation turned out false because one read used an OUTER join where its
siblings used an inner ``Player`` join — the engine really is inert here, and
these tests are what pin that. They also pin *why*: the isolation rests entirely
on the absence of ``Player`` rows and of player ``StatsFact`` rows, which is
exactly what ``ScrimRosterLeakTests`` demonstrates by giving a scrim team one
``Player`` row and watching its captain qualify. A future scrim-roster feature
therefore cannot rely on this staying true.

The waste is real even though the output is empty, which is why
tournament-service stops publishing the event for a scrim at all (see
``tournament-service/tests/test_scrim_recalculation_exclusion.py``); these tests
cover the engine side of the same verdict.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, aggregate_order_by
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from shared.disciplines.overwatch.stats import EVENT_TYPES, STAT_DEFS
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.tournament.player_role import PlayerRole
from shared.testing import create_sqlite_tables

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stats-service"))


models = importlib.import_module("shared.models")
enums = importlib.import_module("shared.core.enums")
achievement = importlib.import_module("shared.models.achievements.achievement")
runner = importlib.import_module("src.services.achievement.engine.runner")
evaluator = importlib.import_module("shared.services.achievements.evaluator")
eval_context = importlib.import_module("shared.domain.achievements.context")
achievement_catalog = importlib.import_module("shared.disciplines.overwatch.achievements.catalog")
_grid_access = importlib.import_module("shared.services.division_grid.access")


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


# SQLite only auto-populates an ``INTEGER PRIMARY KEY`` (a rowid alias), and the
# models' ids are ``BigInteger``.
@compiles(sa.BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "INTEGER"


@compiles(aggregate_order_by, "sqlite")
def _compile_ordered_aggregate_sqlite(element, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return f"{compiler.process(element.target, **kw)} ORDER BY {compiler.process(element.order_by, **kw)}"


TABLE_NAMES = (
    "workspace",
    "division_grid",
    "division_grid_version",
    "division_grid_tier",
    "workspace_division_grid_default",
    "tournament.tournament",
    "tournament.tournament_phase_schedule",
    "tournament.stage",
    "tournament.stage_round_best_of",
    "tournament.stage_item",
    "tournament.team",
    "tournament.player",
    "tournament.player_role",
    "catalog.role_dimension",
    "catalog.role",
    "tournament.bracket_encounter",
    "tournament.standing",
    "stats.match",
    "stats.match_team",
    "stats.match_player",
    "stats.segment",
    "stats.fact",
    "stats.event",
    "stats.stat_def",
    "stats.event_type",
    "catalog.entity",
    "rank.rank_snapshot",
    "registration.registration",
    "registration.role",
    "draft.session",
    "draft.team",
    "draft.player",
    "draft.pick",
    "encounter.scoring_rule",
    "encounter.encounter",
    "encounter.team",
    "encounter.team_member",
    "encounter.game",
    "encounter.game_team",
    "encounter.game_claim",
    "encounter.team_report",
    "encounter.readiness",
    "stats.ingest_job",
    "workspace_member",
    "achievements.rule",
    "achievements.evaluation_result",
    "achievements.evaluation_run",
)

WORKSPACE_ID = 1
REAL_TOURNAMENT_ID = 1
CONTAINER_ID = 2
LATER_TOURNAMENT_ID = 3

# ``players.user`` ids. The scrim captains are real logged-in users with a
# ``players.user`` row and a ``Team.captain_id`` pointing at them — they are just
# not on any roster.
REAL_HOME_USER = 100
REAL_AWAY_USER = 101
SCRIM_HOME_CAPTAIN = 102
SCRIM_AWAY_CAPTAIN = 103

IS_CAPTAIN_RULE = {"type": "is_captain"}


async def overwatch_grid(session):  # noqa: ANN001, ANN201
    """The workspace's Overwatch division grid, as the runner resolves it for an Overwatch rule."""
    return await _grid_access.get_effective_division_grid(session, WORKSPACE_ID, discipline="overwatch")


class _AsyncSavepoint:
    """``async with session.begin_nested()`` over a synchronous savepoint."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._savepoint = None

    async def __aenter__(self):  # noqa: ANN204
        self._savepoint = self._session.begin_nested()
        return self._savepoint

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        if exc_type is None:
            self._savepoint.commit()
        else:
            self._savepoint.rollback()
        return False


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``, as in the analytics sibling."""

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
        return self.sync_session.scalars(statement, *args, **kwargs)

    async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return self.sync_session.get(*args, **kwargs)

    async def flush(self) -> None:
        self.sync_session.flush()

    async def commit(self) -> None:
        self.sync_session.commit()

    async def rollback(self) -> None:
        self.sync_session.rollback()

    def add(self, obj) -> None:  # noqa: ANN001
        self.sync_session.add(obj)

    def begin_nested(self) -> _AsyncSavepoint:
        return _AsyncSavepoint(self.sync_session)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        return getattr(self.sync_session, name)


class _Fixture:
    """An in-memory native-stats fixture using the complete OW vocabulary declarations."""

    def __init__(self) -> None:
        metadata = models.Tournament.__table__.metadata
        tables = [metadata.tables[name] for name in TABLE_NAMES]
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        # The runner and the differ hand ``Uuid`` columns plain strings, which is
        # what asyncpg wants. SQLite is a non-native-uuid dialect, so SQLAlchemy
        # would call ``.hex`` on those strings; claiming native support skips the
        # conversion and lets sqlite3 bind the string as-is.
        self.engine.dialect.supports_native_uuid = True
        # A few columns carry Postgres-cast server defaults (``'[]'::jsonb``)
        # that SQLite cannot parse. They are irrelevant here — every row these
        # tests insert names its own values — so drop them before CREATE.
        for table in tables:
            for column in table.columns:
                default = column.server_default
                if default is not None and "::" in str(getattr(default, "arg", "")):
                    column.server_default = None
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            create_sqlite_tables(conn, tables)
            # The differ reconciles with ``INSERT ... ON CONFLICT DO NOTHING``
            # against a FUNCTIONAL unique index that only a migration creates
            # (``achenc01``). Without it here, SQLite rejects the conflict
            # target and the insert path silently goes untested.
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX achievements.uq_eval_result_dedup_coalesced"
                " ON evaluation_result"
                " (achievement_rule_id, workspace_member_id, COALESCE(tournament_id, 0),"
                " COALESCE(encounter_id, 0), COALESCE(match_id, 0))"
            )
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)
        self._next_id = 1000
        self.insert(
            RoleDimension.__table__,
            id=1,
            discipline="overwatch",
            code="player_role",
            name="Role",
            selection_mode="single",
            rated=True,
        )
        self.role_ids = {code: index for index, code in enumerate(("tank", "damage", "support"), 1)}
        for code, role_id in self.role_ids.items():
            self.insert(CatalogRole.__table__, id=role_id, dimension_id=1, code=code, name=code, attrs={})
        self.stat_ids = {definition.code: index for index, definition in enumerate(STAT_DEFS, 1)}
        for order, definition in enumerate(STAT_DEFS):
            self.insert(
                models.StatDef.__table__,
                id=self.stat_ids[definition.code],
                discipline="overwatch",
                code=definition.code,
                name=definition.name,
                value_format=definition.value_format,
                aggregation=definition.aggregation,
                stat_group=definition.group,
                sort_order=order,
            )
        self.event_ids = {definition.code: index for index, definition in enumerate(EVENT_TYPES, 1)}
        for definition in EVENT_TYPES:
            self.insert(
                models.EventType.__table__,
                id=self.event_ids[definition.code],
                discipline="overwatch",
                code=definition.code,
                name=definition.name,
            )

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def insert(self, table, **values) -> None:  # noqa: ANN001, ANN003
        self.session.execute(sa.insert(table).values(**values))

    def tournament(self, tournament_id: int, *, name: str, is_hidden: bool, start: datetime | None) -> None:
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=WORKSPACE_ID,
            name=name,
            slug=f"tournament-{tournament_id}",
            is_hidden=is_hidden,
            is_league=False,
            start_date=start,
        )

    def member(self, user_id: int, *, workspace_id: int = WORKSPACE_ID) -> int:
        """Get-or-create: ``workspace_member`` is unique on (workspace, player)."""
        existing = self.session.scalar(
            sa.select(models.WorkspaceMember.__table__.c.id).where(
                models.WorkspaceMember.__table__.c.workspace_id == workspace_id,
                models.WorkspaceMember.__table__.c.player_id == user_id,
            )
        )
        if existing is not None:
            return int(existing)
        member_id = self._id()
        self.insert(
            models.WorkspaceMember.__table__,
            id=member_id,
            workspace_id=workspace_id,
            player_id=user_id,
        )
        return member_id

    def team(self, tournament_id: int, name: str, *, captain_id: int | None) -> int:
        team_id = self._id()
        self.insert(
            models.Team.__table__,
            id=team_id,
            tournament_id=tournament_id,
            name=name,
            balancer_name=name,
            captain_id=captain_id,
        )
        return team_id

    def player(
        self,
        tournament_id: int,
        team_id: int,
        member_id: int,
        *,
        name: str,
        is_substitution: bool = False,
        role: str | None = "damage",
        rank: int = 3000,
    ) -> int:
        player_id = self._id()
        self.insert(
            models.Player.__table__,
            id=player_id,
            tournament_id=tournament_id,
            team_id=team_id,
            workspace_member_id=member_id,
            name=name,
            rank=rank,
            is_substitution=is_substitution,
            is_newcomer=False,
            is_newcomer_role=False,
        )
        if role is not None:
            self.insert(PlayerRole.__table__, player_id=player_id, dimension_id=1, role_id=self.role_ids[role])
        return player_id

    def encounter(
        self,
        tournament_id: int,
        first_team_id: int,
        second_team_id: int,
        *,
        stage_id: int | None = None,
        stage_item_id: int | None = None,
        first_score: int = 2,
        second_score: int = 1,
        round_no: int = 1,
        status: object | None = None,
        closeness: float | None = None,
    ) -> int:
        """One duel: the two teams in slots 1 and 2, with the standing a decided series carries."""
        status = enums.EncounterStatus.COMPLETED if status is None else status
        decided = status == enums.EncounterStatus.COMPLETED
        encounter_id = self._id()
        self.insert(
            models.Encounter.__table__,
            id=encounter_id,
            workspace_id=self.session.scalar(
                sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
            ),
            discipline="overwatch",
            tournament_id=tournament_id,
            scoring_rule_id=1,
            name="Encounter",
            slot_count=2,
            best_of=3,
            status=status,
            result_status=enums.EncounterResultStatus.CONFIRMED if decided else enums.EncounterResultStatus.NONE,
            result_source="admin" if decided else None,
            closeness=closeness,
        )
        self.insert(
            models.BracketEncounter.__table__,
            encounter_id=encounter_id,
            tournament_id=tournament_id,
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            round=round_no,
        )
        scores = (first_score, second_score)
        for slot, team_id in enumerate((first_team_id, second_team_id), 1):
            self.insert(
                models.EncounterTeam.__table__,
                id=self._id(),
                encounter_id=encounter_id,
                tournament_id=tournament_id,
                slot=slot,
                team_id=team_id,
                name=f"slot {slot}",
                active=True,
                score=scores[slot - 1],
                # Equal scores share a place, like a drawn series.
                placement=1 + sum(other > scores[slot - 1] for other in scores) if decided else None,
            )
        return encounter_id

    def seat(self, encounter_id: int, team_id: int) -> int:
        """The participation id the team holds in the encounter."""
        table = models.EncounterTeam.__table__
        return int(
            self.session.scalar(
                sa.select(table.c.id).where(
                    table.c.encounter_id == encounter_id, table.c.team_id == team_id, table.c.active.is_(True)
                )
            )
        )

    def replace_seat(self, encounter_id: int, slot: int, team_id: int) -> None:
        """A bracket correction: the occupant of ``slot`` is retired and ``team_id`` takes the seat on."""
        table = models.EncounterTeam.__table__
        retired = self.session.execute(
            sa.select(table).where(table.c.encounter_id == encounter_id, table.c.slot == slot, table.c.active.is_(True))
        ).one()
        self.session.execute(sa.update(table).where(table.c.id == retired.id).values(active=False))
        self.insert(
            table,
            id=self._id(),
            encounter_id=encounter_id,
            tournament_id=retired.tournament_id,
            slot=slot,
            team_id=team_id,
            name=f"slot {slot}",
            active=True,
            score=retired.score,
            placement=retired.placement,
        )

    def match(
        self,
        encounter_id: int,
        home_team_id: int,
        away_team_id: int,
        *,
        home_score: int = 2,
        away_score: int = 1,
        map_id: int = 1,
        time: float | None = None,
        map_index: int | None = None,
    ) -> int:
        encounter = self.session.get(models.Encounter, encounter_id)
        position = map_index
        if position is None:
            position = 1 + (
                self.session.scalar(
                    sa.select(sa.func.max(models.EncounterGame.position)).where(
                        models.EncounterGame.encounter_id == encounter_id
                    )
                )
                or 0
            )
        game_id, match_id = self._id(), self._id()
        self.insert(
            models.EncounterGame.__table__,
            id=game_id,
            encounter_id=encounter_id,
            position=position,
            map_id=map_id,
            state="confirmed",
            result_source=enums.EncounterGameResultSource.ADMIN,
            confirmed_at=sa.func.now(),
        )
        self.insert(
            models.StatsMatch.__table__,
            id=match_id,
            workspace_id=encounter.workspace_id,
            discipline="overwatch",
            encounter_id=encounter_id,
            encounter_game_id=game_id,
            map_entity_id=map_id,
            # As the matchmode01 backfill and ingest do: a match's mode is its map's catalog parent.
            mode_entity_id=self.session.scalar(
                sa.select(models.CatalogEntity.parent_id).where(models.CatalogEntity.id == map_id)
            ),
            duration_s=time if time is not None else 0,
        )
        for source_position, team_id, score in ((1, home_team_id, home_score), (2, away_team_id, away_score)):
            seat = self.seat(encounter_id, team_id)
            self.insert(
                models.EncounterGameTeam.__table__,
                game_id=game_id,
                encounter_id=encounter_id,
                encounter_team_id=seat,
                score=score,
            )
            self.insert(
                models.StatsMatchTeam.__table__,
                match_id=match_id,
                encounter_id=encounter_id,
                encounter_team_id=seat,
                source_position=source_position,
            )
            self.insert(
                models.StatsFact.__table__,
                match_id=match_id,
                encounter_team_id=seat,
                segment=0,
                stat_id=self.stat_ids["score"],
                value=score,
            )
        return match_id

    def observed_player(self, match_id: int, user_id: int, team_id: int) -> tuple[int, int]:
        match = self.session.get(models.StatsMatch, match_id)
        member_id = self.member(user_id, workspace_id=match.workspace_id)
        seat = self.seat(match.encounter_id, team_id)
        player = models.StatsMatchPlayer.__table__
        if not self.session.scalar(
            sa.select(player.c.workspace_member_id).where(
                player.c.match_id == match_id,
                player.c.workspace_member_id == member_id,
            )
        ):
            self.insert(
                player,
                match_id=match_id,
                workspace_member_id=member_id,
                encounter_team_id=seat,
                handle_snapshot=f"Player{user_id}#1234",
            )
        return member_id, seat

    def fact(
        self,
        match_id: int,
        user_id: int,
        team_id: int,
        name: object,
        value: float,
        *,
        segment: int = 0,
        entity_id: int | None = None,
    ) -> None:
        member_id, seat = self.observed_player(match_id, user_id, team_id)
        code = name.value if isinstance(name, enums.LogStatsName) else enums.LogStatsName[str(name)].value
        self.insert(
            models.StatsFact.__table__,
            match_id=match_id,
            workspace_member_id=member_id,
            encounter_team_id=seat,
            stat_id=self.stat_ids[code],
            value=value,
            segment=segment,
            entity_id=entity_id,
        )

    def winning_standing(self, tournament_id: int, team_id: int) -> None:
        self.insert(
            models.Standing.__table__,
            id=self._id(),
            tournament_id=tournament_id,
            team_id=team_id,
            position=1,
            overall_position=1,
            matches=1,
            win=1,
            draw=0,
            lose=0,
            points=1.0,
        )

    def rostered_tournament(self, tournament_id: int) -> dict[str, int]:
        """A real tournament: two teams, both captained, both with a roster."""
        home = self.team(tournament_id, "R home", captain_id=REAL_HOME_USER)
        away = self.team(tournament_id, "R away", captain_id=REAL_AWAY_USER)
        self.player(tournament_id, home, self.member(REAL_HOME_USER), name="home player")
        self.player(tournament_id, away, self.member(REAL_AWAY_USER), name="away player")
        encounter = self.encounter(tournament_id, home, away)
        self.match(encounter, home, away)
        return {"home": home, "away": away, "encounter": encounter}

    def scrim_room(self) -> dict[str, int]:
        """A room exactly as ``services/scrim/service.py:create_room`` leaves it.

        A stage with no items, two teams with ``captain_id`` set and NO ``Player``
        rows, and an observed ``StatsMatch`` without player telemetry.
        """
        stage_id = self._id()
        self.insert(
            models.Stage.__table__,
            id=stage_id,
            scoring_rule_id=1,
            tournament_id=CONTAINER_ID,
            name="room 1",
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            order=1,
            max_rounds=1,
        )
        home = self.team(CONTAINER_ID, "S home", captain_id=SCRIM_HOME_CAPTAIN)
        away = self.team(CONTAINER_ID, "S away", captain_id=SCRIM_AWAY_CAPTAIN)
        self.member(SCRIM_HOME_CAPTAIN)
        self.member(SCRIM_AWAY_CAPTAIN)
        encounter = self.encounter(CONTAINER_ID, home, away, stage_id=stage_id)
        self.match(encounter, home, away)
        return {"stage": stage_id, "home": home, "away": away, "encounter": encounter}

    def rule(
        self,
        rule_id: int,
        slug: str,
        condition_tree: dict,
        depends_on: list[str],
        *,
        grain: str = "user_tournament",
        scope: str = "tournament",
        category: str = "tournament",
        enabled: bool = True,
        min_tournament_id: int | None = None,
    ) -> None:
        self.insert(
            achievement.AchievementRule.__table__,
            id=rule_id,
            workspace_id=WORKSPACE_ID,
            slug=slug,
            discipline="overwatch",
            name=slug,
            description_ru=slug,
            description_en=slug,
            category=category,
            scope=scope,
            grain=grain,
            enabled=enabled,
            condition_tree=condition_tree,
            depends_on=depends_on,
            rule_version=1,
            min_tournament_id=min_tournament_id,
        )


class _EngineTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = _Fixture()

    def tearDown(self) -> None:
        self.db.close()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await overwatch_grid(self.db.shim)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            discipline="overwatch",
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )


class ScrimCaptainAchievementTests(_EngineTestCase):
    """``is_captain`` is the sharpest case: a scrim team DOES have a captain."""

    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        # No start date: the container is provisioned lazily and nothing schedules it.
        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True, start=None)
        self.real = self.db.rostered_tournament(REAL_TOURNAMENT_ID)
        self.room = self.db.scrim_room()
        self.db.session.commit()

    async def test_scrim_captain_does_not_qualify_but_a_real_captain_does(self) -> None:
        scrim = await evaluator.evaluate(self.db.shim, IS_CAPTAIN_RULE, await self.context(CONTAINER_ID))
        real = await evaluator.evaluate(self.db.shim, IS_CAPTAIN_RULE, await self.context(REAL_TOURNAMENT_ID))

        self.assertEqual(set(), scrim)
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID), (REAL_AWAY_USER, REAL_TOURNAMENT_ID)},
            real,
        )

    async def test_no_condition_reaches_a_scrim_captain(self) -> None:
        """Sweep every production rule; none of them may produce 102 or 103.

        Rules whose scope is global legitimately ignore ``context.tournament`` and
        so still return the *rostered* users — that is correct behaviour, not a
        leak. Persist for ``user`` grain is unsliced; a scrim event must not
        publish an evaluation (see tournament-service) rather than relying on
        the old tournament-slice drop.
        """
        context = await self.context(CONTAINER_ID)
        produced: set[int] = set()
        for rule in self._condition_trees():
            try:
                result = await evaluator.evaluate(self.db.shim, rule, context)
            except sa.exc.OperationalError:
                # Dialect-only failure; ``test_no_rule_fails_on_the_scrim_shape``
                # is what proves it is not shape-related.
                self.db.session.rollback()
                continue
            produced.update(row[0] for row in result)

        self.assertEqual(set(), produced & {SCRIM_HOME_CAPTAIN, SCRIM_AWAY_CAPTAIN})
        self.assertTrue(produced, "the sweep must actually produce rows, or it proves nothing")

    async def test_no_rule_fails_on_the_scrim_shape(self) -> None:
        """Every production rule must fail (or not) identically for both shapes.

        A handful of trees raise here because SQLite cannot parse a compound
        ``UNION`` inside a JOIN, which Postgres has no trouble with. Asserting the
        raising set is the SAME for a fully rostered tournament and for the scrim
        container is what separates "this dialect cannot run the query" from
        "an empty tournament breaks the engine" — the distinction the analytics
        bug turned on.
        """
        scrim_failures = await self._failures(await self.context(CONTAINER_ID))
        real_failures = await self._failures(await self.context(REAL_TOURNAMENT_ID))
        self.assertEqual(real_failures, scrim_failures)

    async def _failures(self, context) -> dict[str, str]:  # noqa: ANN001
        failures: dict[str, str] = {}
        for index, rule in enumerate(self._condition_trees()):
            try:
                await evaluator.evaluate(self.db.shim, rule, context)
            except Exception as exc:  # noqa: BLE001
                failures[str(index)] = type(exc).__name__
                self.db.session.rollback()
        return failures

    @staticmethod
    def _condition_trees() -> list[dict]:
        return [
            rule.condition_tree for rule in achievement_catalog.all_default_rules(WORKSPACE_ID) if rule.condition_tree
        ]


class ScrimRosterLeakTests(_EngineTestCase):
    """The isolation rests SOLELY on the absence of ``Player`` rows.

    Same claim the analytics sibling pins for its CTEs. Give one scrim team a
    single ``Player`` row and its captain qualifies immediately — so a future
    "scrim rosters" feature cannot lean on any of this, and cannot lean on
    ``is_hidden`` either, which is not consulted anywhere in the engine.
    """

    async def test_one_player_row_makes_the_scrim_captain_qualify(self) -> None:
        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True, start=None)
        room = self.db.scrim_room()
        self.db.session.commit()

        before = await evaluator.evaluate(self.db.shim, IS_CAPTAIN_RULE, await self.context(CONTAINER_ID))
        self.assertEqual(set(), before)

        self.db.player(
            CONTAINER_ID,
            room["home"],
            self.db.member(SCRIM_HOME_CAPTAIN),
            name="a scrim roster would look like this",
        )
        self.db.session.commit()

        after = await evaluator.evaluate(self.db.shim, IS_CAPTAIN_RULE, await self.context(CONTAINER_ID))
        self.assertEqual({(SCRIM_HOME_CAPTAIN, CONTAINER_ID)}, after)


class ScrimTournamentTimelineTests(_EngineTestCase):
    """The container must not disturb the streak conditions' ordinal timeline.

    ``conditions/streak.py`` ranks the workspace's non-league tournaments with
    ``dense_rank() OVER (ORDER BY start_date NULLS LAST, id)`` — an ordinal
    timeline, so any row that takes a rank BETWEEN two real tournaments splits a
    streak spanning them.

    This used to hold by accident: the container had no start date, so
    ``NULLS LAST`` parked it at the end. It now carries its creation date
    (``TournamentRead`` requires one), so the accident is gone and the
    ``is_hidden`` filter is what keeps the sequence honest. The dated case below
    is the one that fails without that filter.
    """

    async def _streak_users(self) -> set:
        rule = {"type": "consecutive", "params": {"metric": "win", "min_streak": 2}}
        return await evaluator.evaluate(self.db.shim, rule, await self.context(None))

    def _two_won_tournaments(self) -> None:
        for tournament_id in (REAL_TOURNAMENT_ID, LATER_TOURNAMENT_ID):
            self.db.tournament(
                tournament_id,
                name=f"Real {tournament_id}",
                is_hidden=False,
                start=datetime(2026, tournament_id, 1, tzinfo=UTC),
            )
            parts = self.db.rostered_tournament(tournament_id)
            self.db.winning_standing(tournament_id, parts["home"])
        self.db.session.commit()

    async def test_a_dated_container_between_them_does_not_split_the_streak(self) -> None:
        """The real case since the container gained dates: its start date sits
        between the two wins, so an unfiltered timeline ranks it 2nd and the
        streak becomes two runs of one."""
        self._two_won_tournaments()
        without_container = await self._streak_users()
        self.assertEqual({(REAL_HOME_USER,)}, without_container)

        self.db.tournament(
            CONTAINER_ID,
            name="Scrims",
            is_hidden=True,
            start=datetime(2026, REAL_TOURNAMENT_ID, 15, tzinfo=UTC),
        )
        self.db.scrim_room()
        self.db.session.commit()

        self.assertEqual(without_container, await self._streak_users())

    async def test_a_dateless_container_is_still_tolerated(self) -> None:
        """A container provisioned by the shipped version, before ``scrim0002``
        backfilled its dates, must keep working after the filter lands."""
        self._two_won_tournaments()
        without_container = await self._streak_users()

        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True, start=None)
        self.db.scrim_room()
        self.db.session.commit()

        self.assertEqual(without_container, await self._streak_users())


class ScrimEvaluationRunTests(_EngineTestCase):
    """End to end: the run the fan-out would trigger creates and removes nothing.

    This is the "inert" verdict itself. It is also the measurement of the waste
    the tournament-service guard exists to avoid: the run still fetches rules,
    executes one full query per encounter-dependent rule and writes an
    ``EvaluationRun`` audit row, all for an empty result.
    """

    async def test_run_for_a_scrim_creates_nothing_and_removes_nothing(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.tournament(CONTAINER_ID, name="Scrims", is_hidden=True, start=None)
        real = self.db.rostered_tournament(REAL_TOURNAMENT_ID)
        self.db.scrim_room()
        self.db.rule(1, "captain", IS_CAPTAIN_RULE, ["tournament.encounter"])
        # An achievement the real captain already holds. A run aimed at the scrim
        # container must not touch it: an empty result set combined with a
        # mis-scoped diff would delete every stored row for the rule.
        self.db.insert(
            achievement.AchievementEvaluationResult.__table__,
            id=1,
            achievement_rule_id=1,
            workspace_member_id=self.db.session.scalar(
                sa.select(models.WorkspaceMember.__table__.c.id).where(
                    models.WorkspaceMember.__table__.c.player_id == REAL_HOME_USER
                )
            ),
            tournament_id=REAL_TOURNAMENT_ID,
            qualified_at=datetime.now(UTC),
            rule_version=1,
            run_id="00000000-0000-0000-0000-0000000000ff",
            evidence_json={},
        )
        self.db.session.commit()
        self.assertTrue(real["encounter"])

        statements: list[str] = []

        def _record(conn, cursor, statement, *rest):  # noqa: ANN001, ANN002, ANN202
            statements.append(statement)

        sa.event.listen(self.db.engine, "before_cursor_execute", _record)
        try:
            run = await runner.run_evaluation(
                self.db.shim,
                WORKSPACE_ID,
                achievement.EvaluationRunTrigger.parse_complete,
                tournament_id=CONTAINER_ID,
                changed_tables=["tournament.encounter"],
            )
        finally:
            sa.event.remove(self.db.engine, "before_cursor_execute", _record)

        self.assertEqual(achievement.EvaluationRunStatus.done, run.status)
        self.assertEqual(0, run.results_created)
        self.assertEqual(0, run.results_removed)

        # The real captain's achievement is untouched.
        self.assertEqual(
            [(1, REAL_TOURNAMENT_ID)],
            [
                tuple(row)
                for row in self.db.session.execute(
                    sa.select(
                        achievement.AchievementEvaluationResult.__table__.c.achievement_rule_id,
                        achievement.AchievementEvaluationResult.__table__.c.tournament_id,
                    )
                )
            ],
        )
        # ...and nothing was granted inside the container.
        self.assertEqual(
            0,
            self.db.session.scalar(
                sa.select(sa.func.count())
                .select_from(achievement.AchievementEvaluationResult.__table__)
                .where(achievement.AchievementEvaluationResult.__table__.c.tournament_id == CONTAINER_ID)
            ),
        )
        # The cost of that nothing: an audit row and a stack of queries.
        self.assertEqual(
            1,
            self.db.session.scalar(sa.select(sa.func.count()).select_from(achievement.EvaluationRun.__table__)),
        )
        self.assertGreater(len(statements), 10)
