"""The shared sign-up window predicates (plan Decision 10) and their SQL twins.

The rules themselves are pinned on the pure predicates in ``tournament-service/tests/test_registration_node_windows.py``.
What this file adds is what only the shared module owns: the in-Python predicates and the ``FlowNode``-correlated SQL
clauses the aggregate readers use must answer identically for every status, schedule and ``allow_late_registration``,
and the predicates tolerate naive datetimes.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase

import sqlalchemy as sa

from shared.models.tournament.flow import FlowNode, FlowNodeSchedule
from shared.services.registration_window import (
    is_check_in_open,
    is_sign_up_late,
    is_sign_up_open,
    sign_up_late_clause,
    sign_up_open_clause,
    tournament_sign_up_open_clause,
)
from shared.tests.encounter_writer_case import EncounterWriterCase

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)

_STATUSES = ("draft", "open", "check_in", "closed")
#: Every shape of the ``open`` row: none, running, ended, not started, open-ended and running.
_OPEN_ROWS = {
    "none": None,
    "running": (NOW - HOUR, NOW + HOUR),
    "ended": (NOW - 2 * HOUR, NOW - HOUR),
    "upcoming": (NOW + HOUR, None),
    "open_ended": (NOW - HOUR, None),
}


class NaiveDatetimeTests(TestCase):
    def test_naive_timestamps_are_read_as_utc(self) -> None:
        naive = SimpleNamespace(phase="open", starts_at=(NOW - HOUR).replace(tzinfo=None), ends_at=None)
        self.assertTrue(is_sign_up_open("open", [naive], NOW, allow_late=False))
        check_in = SimpleNamespace(phase="check_in", starts_at=(NOW - HOUR).replace(tzinfo=None), ends_at=None)
        self.assertTrue(is_check_in_open("check_in", [check_in], NOW))


class ClauseParityTests(EncounterWriterCase):
    async def test_the_sql_clauses_answer_what_the_predicates_answer(self) -> None:
        cases = list(itertools.product(_STATUSES, _OPEN_ROWS, (False, True)))
        async with self.Session() as s:
            nodes = []
            for status, row_name, allow_late in cases:
                node = FlowNode(
                    tournament_id=self.ids["t"],
                    kind="registration",
                    name=f"{status}/{row_name}/{allow_late}",
                    status=status,
                    config={"allow_late_registration": allow_late},
                )
                s.add(node)
                nodes.append(node)
            await s.flush()
            for node, (_status, row_name, _late) in zip(nodes, cases, strict=True):
                if (bounds := _OPEN_ROWS[row_name]) is not None:
                    s.add(FlowNodeSchedule(node_id=node.id, phase="open", starts_at=bounds[0], ends_at=bounds[1]))
            await s.commit()

            for node, (status, row_name, allow_late) in zip(nodes, cases, strict=True):
                bounds = _OPEN_ROWS[row_name]
                schedule = (
                    [] if bounds is None else [SimpleNamespace(phase="open", starts_at=bounds[0], ends_at=bounds[1])]
                )
                sql_open, sql_late = (
                    await s.execute(
                        sa.select(sign_up_open_clause(NOW), sign_up_late_clause(NOW)).where(FlowNode.id == node.id)
                    )
                ).one()
                with self.subTest(status=status, row=row_name, allow_late=allow_late):
                    self.assertEqual(is_sign_up_open(status, schedule, NOW, allow_late=allow_late), sql_open)
                    self.assertEqual(is_sign_up_late(status, schedule, NOW), sql_late)

    async def test_a_tournament_is_open_when_one_of_its_nodes_is(self) -> None:
        from shared.models.tournament.tournament import Tournament

        async with self.Session() as s:
            s.add(FlowNode(tournament_id=self.ids["t"], kind="registration", name="Day 1", status="closed"))
            await s.flush()
            query = sa.select(Tournament.id).where(Tournament.id == self.ids["t"], tournament_sign_up_open_clause(NOW))
            self.assertIsNone(await s.scalar(query))
            s.add(FlowNode(tournament_id=self.ids["t"], kind="registration", name="Day 2", status="open"))
            await s.flush()
            self.assertEqual(self.ids["t"], await s.scalar(query))
