"""``_run``/``_read`` map every client-caused failure to its own code, and ``_read`` dumps after its session.

- ``_read`` used to miss ``MissingIdentityError``, so an authenticated read without identity answered 500.
- A constraint violation (a race the database settled) used to answer 500 on both runners; a unique violation is
  a 409 and any other constraint a 422, each naming the constraint.
- ``_read`` used to serialize inside the session block, holding a pooled connection through CPU-only work.

No database and no broker: the runners are driven directly with a session fake.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

from shared.rpc.identity import MissingIdentityError

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


helpers = importlib.import_module("src.rpc._helpers")  # noqa: E402


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        self.closed = True
        return False


class _FakeLogger:
    def exception(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"the defensive guard swallowed an error: {args}")


def _integrity_error(sqlstate: str, constraint: str) -> IntegrityError:
    """What asyncpg raises through SQLAlchemy: the adapter error carries the SQLSTATE, its cause the constraint."""
    orig = type("AsyncAdapt_asyncpg_IntegrityError", (Exception,), {})()
    orig.sqlstate = sqlstate
    cause = Exception()
    cause.constraint_name = constraint
    orig.__cause__ = cause
    return IntegrityError("INSERT ...", {}, orig)


class _DumpProbe:
    """A result whose dump reports whether the session was already closed when it ran."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def model_dump(self, **_: Any) -> dict[str, bool]:
        return {"session_closed": self.session.closed}


class RunnerEnvelopeTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.object(helpers.db, "async_session_maker", _FakeSession))

    @staticmethod
    def _raising(exc: BaseException) -> Any:
        async def op(_session: Any) -> Any:
            raise exc

        return op

    async def test_read_answers_a_missing_identity_as_unauthorized(self) -> None:
        envelope = await helpers._read(_FakeLogger(), self._raising(MissingIdentityError("Not authenticated")))

        self.assertFalse(envelope["ok"])
        self.assertEqual("unauthorized", envelope["error"]["code"])

    async def test_unique_violation_is_a_conflict_naming_the_constraint(self) -> None:
        exc = _integrity_error("23505", "uq_team_tournament_name")
        for runner in (helpers._run, helpers._read):
            with self.subTest(runner=runner.__name__):
                envelope = await runner(_FakeLogger(), self._raising(exc))

                self.assertEqual("conflict", envelope["error"]["code"])
                self.assertEqual("uq_team_tournament_name", envelope["error"]["details"]["constraint"])

    async def test_foreign_key_violation_is_unprocessable(self) -> None:
        exc = _integrity_error("23503", "fk_team_tournament_id")
        for runner in (helpers._run, helpers._read):
            with self.subTest(runner=runner.__name__):
                envelope = await runner(_FakeLogger(), self._raising(exc))

                self.assertEqual("unprocessable", envelope["error"]["code"])
                self.assertEqual("fk_team_tournament_id", envelope["error"]["details"]["constraint"])

    async def test_read_dumps_after_the_session_is_closed(self) -> None:
        async def op(session: _FakeSession) -> _DumpProbe:
            return _DumpProbe(session)

        envelope = await helpers._read(_FakeLogger(), op)

        self.assertEqual({"ok": True, "data": {"session_closed": True}}, envelope)
