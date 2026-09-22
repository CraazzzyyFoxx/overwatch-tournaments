"""The in-memory ``AsyncSession`` stand-in the pre-game suites run against.

Extracted from ``test_pregame_loop.py`` so the game-lifecycle suite
(``test_encounter_games.py``) drives the SAME fake: one store that interprets
the query shapes these services issue by walking the SQLAlchemy expression tree
(never by string-matching SQL). Everything it does not know about -- the
seed-resolution lookups (``StageItemInput``/``Stage``/``Standing``) -- answers
empty, which is exactly the "no bracket seeds" path (``decide_seeds`` -> home
acts first).

``ORDER BY``/``FOR UPDATE``/``execution_options`` on a select are ignored: the
store answers in insertion order, so services that need an order sort in Python.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.models.matches.match import Match  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.encounter_game import EncounterGame  # noqa: E402
from shared.models.tournament.encounter_report import EncounterMapReport  # noqa: E402
from shared.models.tournament.encounter_result_audit import EncounterResultAudit  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterPickBanLedger,
    EncounterReadiness,
    PickBanConfig,
    PickBanEntry,
    PickBanSession,
)

__all__ = ("staged_topics", "_matches", "_Result", "_Store")

# Models the store actually holds rows for. Anything else selects empty.
KNOWN_MODELS = (
    PickBanSession,
    PickBanEntry,
    PickBanConfig,
    EncounterReadiness,
    EncounterPickBanLedger,
    EncounterMapReport,
    EncounterGame,
    EncounterResultAudit,
    Match,
    Encounter,
)


def staged_topics(session: Any) -> list[str]:
    """The realtime topics ``emit`` staged on this session, in call order.

    The topic is the whole contract for a pick-ban signal: it names the room
    that must refetch, and the payload adds nothing a subscriber branches on.
    """
    staged = session.info.get("realtime_staged")
    if staged is None:
        return []
    return [scope.domain_topic(data.domain) for scope, data, _actor in staged.domain]


# ── the store ────────────────────────────────────────────────────────────────


def _bound_value(clause: Any) -> Any:
    """The right-hand literal of a comparison, unwrapped from its bind."""
    right = clause.right
    value = getattr(right, "value", right)
    # `col.in_([...])` binds one expanding parameter whose value is the list.
    return value


def _matches(row: Any, clause: Any) -> bool:
    """Whether `row` satisfies `clause`, an ORM WHERE expression.

    Handles the shapes these services build: ``AND`` of comparisons (``=``,
    ``!=``, ``IN``, ``IS NULL``). An ``OR`` is treated as satisfied -- the only
    one here is ``_resolve_config``'s "tournament-wide or this stage" cascade,
    and the fixtures store exactly one config per kind, so narrowing it would
    only re-implement the cascade these tests are not about.
    """
    if clause is None:
        return True
    if isinstance(clause, sa.sql.elements.BooleanClauseList):
        if clause.operator is sa.sql.operators.and_:
            return all(_matches(row, part) for part in clause.clauses)
        return True  # OR — see docstring
    if not isinstance(clause, sa.sql.elements.BinaryExpression):
        return True
    name = getattr(clause.left, "key", None)
    if name is None:
        return True
    actual = getattr(row, name, None)
    operator = clause.operator.__name__
    expected = _bound_value(clause)
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in_op":
        return any(actual == candidate for candidate in expected)
    if operator == "is_":
        return actual is None if expected is None else actual == expected
    if operator in ("is_not", "isnot"):
        return actual is not None if expected is None else actual != expected
    raise AssertionError(f"unsupported operator in fake store: {operator}")


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def unique(self) -> _Result:
        # `shared.repository` reads go through `result.unique().scalars()`, so the
        # store has to answer it -- a no-op here (no joined eager loads).
        return self

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _Store:
    """In-memory stand-in for ``AsyncSession`` over the pick-ban tables."""

    def __init__(self) -> None:
        self.rows: dict[type, list[Any]] = {}
        self.info: dict[Any, Any] = {}
        self._next_id = 1

    # -- seeding / bookkeeping --------------------------------------------
    def seed(self, *instances: Any) -> None:
        for instance in instances:
            self.add(instance)
        self._assign_ids()

    def all_of(self, model: type) -> list[Any]:
        return list(self.rows.get(model, []))

    def add(self, instance: Any) -> None:
        self.rows.setdefault(type(instance), []).append(instance)

    def _assign_ids(self) -> None:
        for model, rows in self.rows.items():
            for row in rows:
                if getattr(row, "id", None) is None:
                    row.id = self._next_id
                    self._next_id += 1
                # A real flush resolves a relationship-only insert into its FK;
                # every query here filters on the FK column.
                owner = getattr(row, "session", None)
                if model is PickBanEntry and getattr(row, "session_id", None) is None and owner is not None:
                    row.session_id = owner.id

    async def flush(self) -> None:
        self._assign_ids()

    async def commit(self) -> None:
        self._assign_ids()

    async def rollback(self) -> None:  # pragma: no cover - nothing raises here
        return None

    async def refresh(self, instance: Any) -> None:
        return None

    async def get(self, model: type, pk: Any) -> Any:
        return next((row for row in self.rows.get(model, []) if getattr(row, "id", None) == pk), None)

    # -- querying ---------------------------------------------------------
    def _entity(self, statement: Any) -> Any:
        return statement.column_descriptions[0]["entity"]

    def _select_rows(self, statement: Any) -> list[Any]:
        entity = self._entity(statement)
        rows = [row for row in self.rows.get(entity, []) if _matches(row, statement.whereclause)]
        descriptions = statement.column_descriptions
        if len(descriptions) == 1 and descriptions[0]["expr"] is entity:
            return rows
        columns = [description["name"] for description in descriptions]
        if len(columns) == 1:
            return [getattr(row, columns[0]) for row in rows]
        return [tuple(getattr(row, column) for column in columns) for row in rows]

    async def execute(self, statement: Any) -> _Result:
        if isinstance(statement, sa.sql.dml.Delete):
            model = next(
                (model for model in self.rows if model.__tablename__ == statement.table.name),
                None,
            )
            if model is not None:
                self.rows[model] = [row for row in self.rows[model] if not _matches(row, statement.whereclause)]
            return _Result([])
        entity = self._entity(statement)
        if entity is not None and entity not in self.rows and entity not in KNOWN_MODELS:
            # Seed resolution's bracket/standings lookups: nothing stored, which
            # is the "no seeds, home acts first" path.
            return _Result([])
        return _Result(self._select_rows(statement))

    async def scalar(self, statement: Any) -> Any:
        # `select(func.count()).select_from(X).where(...)` — the only aggregate
        # these services issue.
        if statement.column_descriptions[0]["entity"] is None:
            froms = statement.get_final_froms()
            model = next((model for model in self.rows if model.__tablename__ == froms[0].name), None)
            if model is None:
                return 0
            return sum(1 for row in self.rows[model] if _matches(row, statement.whereclause))
        rows = self._select_rows(statement)
        return rows[0] if rows else None
