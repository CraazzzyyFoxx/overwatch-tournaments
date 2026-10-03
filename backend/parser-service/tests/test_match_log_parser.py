from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

enums = importlib.import_module("src.core.enums")
flows = importlib.import_module("src.services.match_logs.flows")
models = importlib.import_module("src.models")


class MatchLogParserTests(TestCase):
    def test_wide_player_stat_row_is_not_truncated_or_shifted(self) -> None:
        tournament = SimpleNamespace(id=1, name="Test Cup")
        stat_payload = [
            "1",
            "Blue Team",
            "Player One",
            "Ana",
            *[str(index) for index in range(33)],
        ]
        line = ",".join(["2026-04-19T12:00:00Z", "player_stat", "12.5", *stat_payload])

        processor = flows.MatchLogProcessor(tournament, "match.log", [line], SimpleNamespace())

        rows = processor._get_rows(enums.LogEventType.PlayerStat)
        self.assertEqual(1, len(rows))
        self.assertEqual(stat_payload, rows.iloc[0]["data"])

    def test_quoted_commas_and_type_index_survive_batched_csv_parse(self) -> None:
        tournament = SimpleNamespace(id=1, name="Test Cup")
        lines = [
            "2026-04-19T12:00:00Z,meta,0,ignored",
            '2026-04-19T12:00:00Z,match_start,0.0,Ilios,"Control","Team, A","Team, B"',
            "2026-04-19T12:00:00Z,not_a_real_event,1.0,x",
            "2026-04-19T12:00:00Z,kill,12.5,Team A,Ana,Ana,Team B,Mercy,Mercy,0,100,False,False",
        ]
        processor = flows.MatchLogProcessor(tournament, "match.log", lines, SimpleNamespace())

        starts = processor._get_rows(enums.LogEventType.MatchStart)
        self.assertEqual(1, len(starts))
        self.assertEqual(["Ilios", "Control", "Team, A", "Team, B"], starts.iloc[0]["data"])
        self.assertEqual(1, len(processor._get_rows(enums.LogEventType.Kill)))
        self.assertTrue(processor._get_rows(enums.LogEventType.PlayerStat).empty)


class BulkInsertTests(IsolatedAsyncioTestCase):
    """A match's stat rows go out as ONE statement, hero or no hero.

    ``sa.insert(MatchStatistics)`` (the ORM-entity form) drops ``hero_id`` from
    the statement whenever its value is ``None`` and starts a fresh batch every
    time that column set changes, so a match's rows left in pivot order were
    emitted a few at a time (Sentry OWT-TOURNAMENTS-2BV).
    """

    async def test_rows_with_and_without_hero_share_one_statement(self) -> None:
        engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        statements: list[tuple[str, bool]] = []

        @sa.event.listens_for(engine, "before_cursor_execute")
        def _record(_conn, _cursor, statement, _params, _ctx, executemany):  # noqa: ANN001, ANN202
            statements.append((statement, executemany))

        with engine.begin() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS matches")
            # Hand-written DDL, not ``__table__.create``: SQLite only
            # autoincrements an INTEGER primary key, and the model's is BIGINT.
            conn.exec_driver_sql(
                "CREATE TABLE matches.statistics (id INTEGER PRIMARY KEY, match_id BIGINT, round INTEGER,"
                " team_id BIGINT, user_id BIGINT, hero_id BIGINT, name VARCHAR, value FLOAT)"
            )
        statements.clear()

        rows = [
            {"match_id": 1, "round": 1, "team_id": 2, "user_id": 3, "hero_id": None, "name": name, "value": value}
            for name, value in ((enums.LogStatsName.Eliminations, 4.0), (enums.LogStatsName.Deaths, 1.0))
        ]
        rows.insert(1, {**rows[0], "hero_id": 9, "name": enums.LogStatsName.HeroTimePlayed, "value": 60.0})

        with Session(engine) as session:
            await flows._bulk_insert(SimpleNamespace(execute=_sync_execute(session)), models.MatchStatistics, rows)
            session.commit()
            stored = session.execute(
                sa.select(models.MatchStatistics.hero_id, models.MatchStatistics.value).order_by(
                    models.MatchStatistics.value
                )
            ).all()

        self.assertEqual([(None, 1.0), (None, 4.0), (9, 60.0)], [(hero_id, value) for hero_id, value in stored])
        inserts = [(statement, many) for statement, many in statements if statement.lstrip().startswith("INSERT")]
        self.assertEqual(1, len(inserts), inserts)
        self.assertTrue(inserts[0][1], "the batch must go out as one executemany")
        self.assertIn("hero_id", inserts[0][0])


def _sync_execute(session: Session):  # noqa: ANN202
    async def execute(statement, params=None):  # noqa: ANN001, ANN202
        return session.execute(statement, params)

    return execute
