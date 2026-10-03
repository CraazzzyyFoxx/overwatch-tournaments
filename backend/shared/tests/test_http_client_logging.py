"""Outbound-failure logging decides how many Sentry issues one outage opens.

Loguru ERROR records become Sentry events whose title is the rendered message
(``event_format="{message}"`` in ``shared.observability.sentry``), and a
message-only record groups by that message. With the request path in it, one
OverFast outage opened an issue per player URL (2993 events in two weeks) and
the breaker's own fast-fail opened a second pile on top. These tests pin the
shape: the message names the host and the error type only, the varying parts
ride along as structured extras, and a fast-fail is not an error.
"""

from __future__ import annotations

import asyncio
from unittest import TestCase

import httpx
from loguru import logger

from shared.clients.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from shared.clients.http_client import ResilientHttpClient

BASE_URL = "https://overfast.example.test"
PATH = "/players/Player-1234/summary"


class _FailingTransport:
    """Stands in for ``httpx.AsyncClient`` inside the started client."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        raise self._exc


class _Records:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self._id: int | None = None

    def __enter__(self) -> _Records:
        self._id = logger.add(lambda m: self.records.append(m.record), level="DEBUG", format="{message}")
        return self

    def __exit__(self, *exc: object) -> None:
        logger.remove(self._id)

    def at(self, level: str) -> list[dict]:
        return [r for r in self.records if r["level"].name == level]


class OutboundFailureLoggingTests(TestCase):
    def _client(self, exc: Exception, breaker: CircuitBreaker | None = None) -> ResilientHttpClient:
        client = ResilientHttpClient(base_url=BASE_URL, circuit_breaker=breaker)
        client._client = _FailingTransport(exc)  # type: ignore[assignment]
        return client

    def test_upstream_error_message_is_stable_per_host_and_error_type(self) -> None:
        # ReadError is not retried, so the breaker sees exactly one failure.
        client = self._client(httpx.ReadError("boom"))

        with _Records() as captured:
            with self.assertRaises(httpx.ReadError):
                asyncio.run(client.request("GET", PATH))

        errors = captured.at("ERROR")
        self.assertEqual(len(errors), 1)
        record = errors[0]
        self.assertEqual(record["message"], f"GET {BASE_URL} failed: ReadError")
        self.assertNotIn(PATH, record["message"])
        self.assertEqual(record["extra"]["path"], PATH)
        self.assertEqual(record["extra"]["detail"], "boom")

    def test_circuit_breaker_fast_fail_is_not_an_error(self) -> None:
        breaker = CircuitBreaker(name=BASE_URL, failure_threshold=1, recovery_timeout=60.0)
        client = self._client(httpx.ReadError("boom"), breaker=breaker)

        async def scenario() -> None:
            with self.assertRaises(httpx.ReadError):
                await client.request("GET", PATH)
            with self.assertRaises(CircuitBreakerOpen):
                await client.request("GET", "/players/Other-5678/summary")

        with _Records() as captured:
            asyncio.run(scenario())

        # One ERROR for the real failure (plus the breaker's own "opened" line,
        # emitted first from inside ``CircuitBreaker.call``), none for the
        # blocked request.
        self.assertEqual(
            [r["message"] for r in captured.at("ERROR")],
            [
                f"Circuit breaker for {BASE_URL} opened after 1 consecutive failures",
                f"GET {BASE_URL} failed: ReadError",
            ],
        )
        skipped = [r for r in captured.at("DEBUG") if "circuit breaker open" in r["message"]]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["extra"]["path"], "/players/Other-5678/summary")
