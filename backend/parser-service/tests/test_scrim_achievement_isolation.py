"""A completed scrim must not award, remove, or crash on an achievement.

Design: ``docs/plans/2026-08-12-scrim-rooms.md`` §5.

When both captains agree on a scrim's result, tournament-service publishes an
``EncounterCompletedEvent`` and parser-service republishes it as an
``AchievementEvaluateEvent`` pointed at the scrim's *container* tournament
(``serve.py:368-398``), so ``runner.run_evaluation`` runs against a tournament
with two ``Team`` rows, no ``Player`` rows, no ``Standing`` rows, no stage items,
no ``division_grid_version_id`` and a NULL ``start_date``.

Unlike ``analytics/service.py:get_matches`` — where the same "it will be inert"
expectation turned out false because one read used an OUTER join where its
siblings used an inner ``Player`` join — the engine really is inert here, and
these tests are what pin that. They also pin *why*: the isolation rests entirely
on the absence of ``Player`` rows and of ``MatchStatistics`` rows, which is
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))


models = importlib.import_module("src.models")
enums = importlib.import_module("shared.core.enums")
achievement = importlib.import_module("shared.models.achievements.achievement")
runner = importlib.import_module("src.services.achievement.engine.runner")
evaluator = importlib.import_module("src.services.achievement.engine.evaluator")
eval_context = importlib.import_module("src.services.achievement.engine.context")
achievement_catalog = importlib.import_module("src.domain.achievement_catalog")


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


TABLE_NAMES = (
    "workspace",
    "division_grid",
    "division_grid_version",
    "division_grid_tier",
    "tournament.tournament",
    "tournament.tournament_phase_schedule",
    "tournament.stage",
    "tournament.stage_item",
    "tournament.team",
    "tournament.player",
    "tournament.encounter",
    "tournament.standing",
    "matches.match",
    "matches.statistics",
    "matches.kill_feed",
    "matches.event",
    "overwatch.gamemode",
    "overwatch.map",
    "overwatch.hero",
    "overwatch_rank.rank_snapshot",
    "balancer.registration",
    "balancer.registration_role",
    "balancer.draft_session",
    "balancer.draft_team",
    "balancer.draft_player",
    "balancer.draft_pick",
    "tournament.encounter_captain_report",
    "tournament.encounter_map_report",
    "tournament.encounter_map_code",
    "tournament.encounter_readiness",
    "log_processing.record",
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
    """A throwaway in-memory database plus row builders for it."""

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
            for table in tables:
                table.create(conn)
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

    def member(self, user_id: int) -> int:
        """Get-or-create: ``workspace_member`` is unique on (workspace, player)."""
        existing = self.session.scalar(
            sa.select(models.WorkspaceMember.__table__.c.id).where(
                models.WorkspaceMember.__table__.c.workspace_id == WORKSPACE_ID,
                models.WorkspaceMember.__table__.c.player_id == user_id,
            )
        )
        if existing is not None:
            return int(existing)
        member_id = self._id()
        self.insert(
            models.WorkspaceMember.__table__,
            id=member_id,
            workspace_id=WORKSPACE_ID,
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
        self, tournament_id: int, team_id: int, member_id: int, *, name: str, is_substitution: bool = False
    ) -> int:
        player_id = self._id()
        self.insert(
            models.Player.__table__,
            id=player_id,
            tournament_id=tournament_id,
            team_id=team_id,
            workspace_member_id=member_id,
            name=name,
            role=enums.HeroClass.damage,
            rank=3000,
            is_substitution=is_substitution,
            is_newcomer=False,
            is_newcomer_role=False,
        )
        return player_id

    def encounter(
        self,
        tournament_id: int,
        home_team_id: int,
        away_team_id: int,
        *,
        stage_id: int | None = None,
    ) -> int:
        encounter_id = self._id()
        self.insert(
            models.Encounter.__table__,
            id=encounter_id,
            tournament_id=tournament_id,
            stage_id=stage_id,
            name="Encounter",
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=2,
            away_score=1,
            round=1,
            best_of=3,
            status=enums.EncounterStatus.COMPLETED,
        )
        return encounter_id

    def match(self, encounter_id: int, home_team_id: int, away_team_id: int) -> int:
        match_id = self._id()
        self.insert(
            models.Match.__table__,
            id=match_id,
            encounter_id=encounter_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=2,
            away_score=1,
            map_id=1,
        )
        return match_id

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
        rows, and a captain-reported ``Match`` — real, but never log-parsed, so no
        ``MatchStatistics``.
        """
        stage_id = self._id()
        self.insert(
            models.Stage.__table__,
            id=stage_id,
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
        grid = await runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
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
            rule.condition_tree for rule in achievement_catalog._all_default_rules(WORKSPACE_ID) if rule.condition_tree
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
