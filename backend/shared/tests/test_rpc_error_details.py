"""Unit tests for the machine-readable ``error.details`` companion to ``message``.

``message`` is what a human reads; everything a client can branch on (per-item
codes, field paths, ``Retry-After``) used to be flattened into it or dropped
outright. These tests pin the split: the strings keep their old shape, the
structure now rides ``details``.

Runs under stdlib unittest with a fake session factory, so no database is needed.
"""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase

from pydantic import BaseModel, ValidationError

from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.common import envelope, field_entry, http_error, retry_after_seconds, validation_error
from shared.schemas.rpc import parse_rpc, rpc_error, rpc_ok


class _Payload(BaseModel):
    name: str
    size: int


def _validation_exc() -> ValidationError:
    try:
        _Payload.model_validate({"size": "big"})
    except ValidationError as exc:
        return exc
    raise AssertionError("payload was expected to be invalid")


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


def _session_factory() -> _FakeSession:
    return _FakeSession()


class RpcErrorTests(IsolatedAsyncioTestCase):
    def test_two_arg_call_omits_details(self) -> None:
        # The overwhelming majority of call sites carry nothing structured; they
        # must not start shipping an empty object that means "look in here".
        self.assertEqual(
            rpc_error("forbidden", "nope"),
            {"ok": False, "error": {"code": "forbidden", "message": "nope"}},
        )

    def test_empty_details_omitted(self) -> None:
        self.assertNotIn("details", rpc_error("forbidden", "nope", {})["error"])

    def test_details_included_when_present(self) -> None:
        error = rpc_error("rate_limited", "slow down", {"retry_after": 30})["error"]
        self.assertEqual(error["details"], {"retry_after": 30})

    def test_rpc_ok_omits_empty_warnings(self) -> None:
        self.assertEqual(rpc_ok({"id": 1}), {"ok": True, "data": {"id": 1}})
        self.assertEqual(rpc_ok({"id": 1}, []), {"ok": True, "data": {"id": 1}})

    def test_rpc_ok_includes_warnings(self) -> None:
        body = rpc_ok({"id": 1}, [{"code": "truncated", "message": "capped"}])
        self.assertEqual(
            body,
            {
                "ok": True,
                "data": {"id": 1},
                "warnings": [{"code": "truncated", "message": "capped"}],
            },
        )


class ParseRpcTests(IsolatedAsyncioTestCase):
    def test_rejects_non_envelope(self) -> None:
        self.assertIsNone(parse_rpc(None))
        self.assertIsNone(parse_rpc("nope"))
        self.assertIsNone(parse_rpc({"members": {}}))

    def test_ok_with_warnings(self) -> None:
        reply = parse_rpc(rpc_ok({"id": 1}, [{"code": "truncated", "message": "capped"}]))
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertTrue(reply.ok)
        self.assertEqual(reply.data, {"id": 1})
        self.assertEqual(reply.warnings[0]["code"], "truncated")

    def test_error(self) -> None:
        reply = parse_rpc(rpc_error("not_found", "missing", {"retry_after": 1}))
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertFalse(reply.ok)
        self.assertEqual(reply.code, "not_found")
        self.assertEqual(reply.message, "missing")
        self.assertEqual(reply.error["details"], {"retry_after": 1})


class HttpErrorTests(IsolatedAsyncioTestCase):
    def test_api_exception_keeps_every_item_code(self) -> None:
        exc = ApiHTTPException(
            status_code=409,
            detail=[ApiExc(msg="team is full", code="team_full"), ApiExc(msg="roster locked", code="roster_locked")],
        )
        message, details = http_error(exc)
        self.assertEqual(message, "team is full; roster locked")
        self.assertEqual(
            details["fields"],
            [
                {"field": None, "msg": "team is full", "code": "team_full"},
                {"field": None, "msg": "roster locked", "code": "roster_locked"},
            ],
        )

    def test_api_exc_carries_the_field_an_error_is_about(self) -> None:
        assert ApiExc(msg="m", code="c", field="f").model_dump(mode="json") == {"msg": "m", "code": "c", "field": "f"}

    def test_string_detail_has_no_details(self) -> None:
        self.assertEqual(http_error(HTTPException(status_code=404, detail="Team not found")), ("Team not found", {}))

    def test_retry_after_header_becomes_int(self) -> None:
        # A worker cannot set an HTTP header; the gateway re-emits it from here.
        exc = HTTPException(
            status_code=429,
            detail="Balancer rate limit exceeded: requests_per_minute",
            headers={"Retry-After": "30"},
        )
        message, details = http_error(exc)
        self.assertEqual(message, "Balancer rate limit exceeded: requests_per_minute")
        self.assertEqual(details, {"retry_after": 30})

    def test_unparsable_retry_after_is_dropped(self) -> None:
        exc = HTTPException(status_code=429, detail="slow", headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        self.assertIsNone(retry_after_seconds(exc))
        self.assertEqual(http_error(exc)[1], {})

    def test_no_headers_at_all(self) -> None:
        self.assertIsNone(retry_after_seconds(HTTPException(status_code=400, detail="bad")))


class ValidationDetailTests(IsolatedAsyncioTestCase):
    def test_message_is_a_summary_not_the_repr(self) -> None:
        message, details = validation_error(_validation_exc())
        self.assertEqual(message, "name: Field required")
        self.assertNotIn("validation error for", message)
        self.assertEqual(
            details["fields"],
            [
                {"field": "name", "msg": "Field required", "code": "missing"},
                {
                    "field": "size",
                    "msg": "Input should be a valid integer, unable to parse string as an integer",
                    "code": "int_parsing",
                },
            ],
        )

    def test_body_and_payload_are_stripped_from_the_field_path(self) -> None:
        # A nested field arrives as ("body", "config", "size"); the client knows it
        # as "config.size" -- the wrapper names where the value travelled, not what
        # it is called.
        entry = field_entry({"loc": ("body", "config", "size"), "msg": "too big", "type": "less_than"})
        self.assertEqual(entry, {"field": "config.size", "msg": "too big", "code": "less_than"})


class EnvelopeTests(IsolatedAsyncioTestCase):
    async def _run(self, op: Any) -> dict[str, Any]:
        return await envelope(_FakeLogger(), "test", op, session_factory=_session_factory)

    async def test_http_exception_branch_carries_details(self) -> None:
        async def op(session: Any) -> Any:
            raise ApiHTTPException(status_code=409, detail=[ApiExc(msg="team is full", code="team_full")])

        res = await self._run(op)
        self.assertEqual(res["error"]["code"], "conflict")
        self.assertEqual(res["error"]["message"], "team is full")
        self.assertEqual(res["error"]["details"]["fields"][0]["code"], "team_full")

    async def test_validation_branch_carries_details(self) -> None:
        async def op(session: Any) -> Any:
            raise _validation_exc()

        res = await self._run(op)
        self.assertEqual(res["error"]["code"], "unprocessable")
        self.assertEqual(res["error"]["message"], "name: Field required")
        self.assertEqual(len(res["error"]["details"]["fields"]), 2)

    async def test_success_is_untouched(self) -> None:
        async def op(session: Any) -> Any:
            return {"id": 1}

        self.assertEqual(await self._run(op), {"ok": True, "data": {"id": 1}})


class _FakeLogger:
    def exception(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("no unexpected exception should reach the defensive guard")
