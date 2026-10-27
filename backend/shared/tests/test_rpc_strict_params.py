"""A bad query value is a 422, and a constraint violation is a 409/422 — never a dropped filter or a 500.

Runs under stdlib unittest with a fake session factory, so no database is needed.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase

from sqlalchemy.exc import IntegrityError

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.common import envelope, integrity_error, q1


def _query(**params: str) -> dict:
    return {"query": {key: [value] for key, value in params.items()}}


def _integrity(sqlstate: str, constraint: str | None = "uq_team_name") -> IntegrityError:
    """What SQLAlchemy's asyncpg adapter raises: the DBAPI error carries ``sqlstate``, its cause the constraint."""
    orig = type("AdaptedIntegrityError", (Exception,), {})("violation")
    orig.sqlstate = sqlstate
    cause = Exception("asyncpg")
    cause.constraint_name = constraint
    orig.__cause__ = cause
    return IntegrityError("INSERT ...", {}, orig)


class StrictQueryParamTests(TestCase):
    def test_a_value_the_cast_rejects_is_a_422_not_the_default(self) -> None:
        for cast, raw in ((int, "abc"), (int, ""), (datetime.date.fromisoformat, "yesterday")):
            with self.assertRaises(HTTPException) as caught:
                q1(_query(x=raw), "x", cast, 7)
            self.assertEqual(422, caught.exception.status_code)
            self.assertEqual("x", caught.exception.detail["field"])

    def test_missing_still_means_the_default_and_good_values_cast(self) -> None:
        self.assertEqual(7, q1({}, "x", int, 7))
        self.assertEqual(3, q1(_query(x="3"), "x", int, 7))
        self.assertEqual("abc", q1(_query(x="abc"), "x"))


class IntegrityErrorTests(TestCase):
    def test_unique_violation_is_a_conflict(self) -> None:
        self.assertEqual(
            ("conflict", "Already exists", {"constraint": "uq_team_name"}), integrity_error(_integrity("23505"))
        )

    def test_foreign_key_check_and_not_null_violations_are_unprocessable(self) -> None:
        for sqlstate in ("23503", "23514", "23502"):
            code, _message, details = integrity_error(_integrity(sqlstate, "fk_x"))
            self.assertEqual(("unprocessable", {"constraint": "fk_x"}), (code, details))

    def test_an_unnamed_constraint_carries_no_details(self) -> None:
        self.assertEqual({}, integrity_error(_integrity("23505", None))[2])

    def test_anything_but_an_integrity_error_is_not_mapped(self) -> None:
        for exc in (ValueError("x"), HTTPException(status_code=409, detail="x"), _integrity("23505").orig):
            with self.subTest(exc=type(exc).__name__):
                self.assertIsNone(integrity_error(exc))


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[tuple] = []

    def warning(self, *args: Any) -> None:
        self.warnings.append(args)

    def exception(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("a constraint violation must not reach the defensive 500 guard")


class EnvelopeMappingTests(IsolatedAsyncioTestCase):
    async def _run(self, op: Any) -> dict[str, Any]:
        return await envelope(_Logger(), "test", op, session_factory=_FakeSession)

    async def test_a_lost_unique_race_answers_409(self) -> None:
        async def op(session: Any) -> Any:
            raise _integrity("23505")

        res = await self._run(op)
        self.assertEqual("conflict", res["error"]["code"])
        self.assertEqual({"constraint": "uq_team_name"}, res["error"]["details"])

    async def test_a_bad_query_value_answers_422(self) -> None:
        async def op(session: Any) -> Any:
            return q1(_query(workspace_id="all"), "workspace_id", int)

        res = await self._run(op)
        self.assertEqual("unprocessable", res["error"]["code"])
        self.assertEqual("workspace_id", res["error"]["details"]["fields"][0]["field"])
