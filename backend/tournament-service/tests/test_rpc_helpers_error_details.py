"""``_run``/``_read`` must ship ``ApiExc.code``/``.field``, not a Python repr.

Every tournament-service RPC subject answers through one of these two runners,
so what they do with an exception IS the service's error contract. They used to
map ``ApiHTTPException`` with ``rpc_error(code, str(exc.detail))`` -- and
``exc.detail`` is a *list* of ``ApiExc``, so the whole per-item structure
reached the browser as ``"[{'msg': 'Invalid format.', 'code': 'invalid_format',
'field': 'battle_tag'}]"``: one string, in a key (``detail``) the frontend can
only render as a banner. The registration form's per-field errors, which are
addressed by ``field`` and translated by ``code``, all landed as one generic
message.

The fix is to use the same ``shared.rpc.common`` mapping every other worker
already uses, which puts the items under ``details["fields"]`` -- the key the
gateway relays verbatim into the error body.

No database and no broker: the runners are driven directly with a session fake.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from pydantic import BaseModel, ValidationError

from shared.core.errors import ApiExc, ApiHTTPException

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

helpers = importlib.import_module("src.rpc._helpers")  # noqa: E402


class _Answers(BaseModel):
    battle_tag: str


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _FakeLogger:
    def exception(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"the defensive guard swallowed an error: {args}")


#: The rejection a registration PATCH produces: two bad answers, each naming the
#: answer key it belongs to.
FIELD_ERRORS = [
    ApiExc(msg="Invalid format.", code="invalid_format", field="battle_tag"),
    ApiExc(msg="Not one of the options.", code="invalid_option", field="server"),
]


class RunnerErrorDetailTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.enterContext(patch.object(helpers.db, "async_session_maker", _FakeSession))

    async def _run(self, exc: BaseException) -> dict[str, Any]:
        async def op(_session: Any) -> Any:
            raise exc

        return await helpers._run(_FakeLogger(), op)

    async def _read(self, exc: BaseException) -> dict[str, Any]:
        async def op(_session: Any) -> Any:
            raise exc

        return await helpers._read(_FakeLogger(), op)

    async def test_run_keeps_every_items_code_and_field(self) -> None:
        envelope = await self._run(ApiHTTPException(status_code=422, detail=FIELD_ERRORS))

        self.assertEqual("unprocessable", envelope["error"]["code"])
        self.assertEqual(
            [
                {"field": "battle_tag", "msg": "Invalid format.", "code": "invalid_format"},
                {"field": "server", "msg": "Not one of the options.", "code": "invalid_option"},
            ],
            envelope["error"]["details"]["fields"],
        )

    async def test_run_message_is_human_text_not_a_repr(self) -> None:
        envelope = await self._run(ApiHTTPException(status_code=422, detail=FIELD_ERRORS))

        message = envelope["error"]["message"]
        self.assertEqual("Invalid format.; Not one of the options.", message)
        # The old behaviour: str() of the detail list. A client parsing this for a
        # field name is parsing a Python literal over the wire.
        self.assertNotIn("{", message)

    async def test_read_keeps_the_same_structure(self) -> None:
        envelope = await self._read(
            ApiHTTPException(
                status_code=409, detail=[ApiExc(msg="Reload.", code="form_version_stale", field="form_version_id")]
            )
        )

        self.assertEqual("conflict", envelope["error"]["code"])
        self.assertEqual("Reload.", envelope["error"]["message"])
        self.assertEqual(
            [{"field": "form_version_id", "msg": "Reload.", "code": "form_version_stale"}],
            envelope["error"]["details"]["fields"],
        )

    async def test_string_detail_still_reaches_the_client_verbatim(self) -> None:
        envelope = await self._run(helpers.HTTPException(status_code=404, detail="Tournament not found"))

        self.assertEqual("not_found", envelope["error"]["code"])
        self.assertEqual("Tournament not found", envelope["error"]["message"])
        self.assertNotIn("details", envelope["error"])

    async def test_validation_error_names_the_field_instead_of_dumping_the_repr(self) -> None:
        try:
            _Answers(battle_tag=None)
        except ValidationError as exc:
            envelope = await self._run(exc)
        else:  # pragma: no cover - the model rejects None
            raise AssertionError("payload was expected to be invalid")

        self.assertEqual("unprocessable", envelope["error"]["code"])
        self.assertNotIn("validation error for", envelope["error"]["message"])
        self.assertEqual("battle_tag", envelope["error"]["details"]["fields"][0]["field"])
