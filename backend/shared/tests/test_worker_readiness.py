"""A worker's ``GET /health`` reflects the broker connection and the consumers, not that Python is up."""

from __future__ import annotations

import asyncio
import socket
import urllib.error
import urllib.request
from types import SimpleNamespace

from shared.observability import Readiness, start_worker_metrics_server


class _Broker:
    def __init__(self, *, connected: bool = True, running: tuple[bool, ...] = (True, True)) -> None:
        self.connected = connected
        self.subscribers = [SimpleNamespace(queue=f"q{i}", running=state) for i, state in enumerate(running)]

    async def ping(self, timeout: float) -> bool:
        return self.connected


def _probe(readiness: Readiness) -> tuple[bool, str]:
    """Ask from a foreign thread while a loop runs, as the metrics listener does."""

    async def main() -> tuple[bool, str]:
        readiness.bind()
        readiness.serving(True)
        return await asyncio.to_thread(readiness)

    return asyncio.run(main())


def test_not_ready_until_the_process_says_it_is_serving() -> None:
    readiness = Readiness(_Broker())

    assert readiness() == (False, "not serving")

    async def main() -> tuple[bool, str]:
        readiness.bind()
        return await asyncio.to_thread(readiness)

    assert asyncio.run(main()) == (False, "not serving")


def test_ready_when_the_broker_answers_and_every_consumer_runs() -> None:
    assert _probe(Readiness(_Broker())) == (True, "ok")


def test_not_ready_when_the_broker_is_unreachable() -> None:
    assert _probe(Readiness(_Broker(connected=False))) == (False, "broker unreachable")


def test_not_ready_when_a_consumer_stopped() -> None:
    ok, detail = _probe(Readiness(_Broker(running=(True, False))))

    assert not ok and detail == "consumers not running: q1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_the_metrics_listener_answers_health_with_the_probe_and_still_serves_metrics(monkeypatch) -> None:
    from shared.observability import worker

    monkeypatch.setattr(worker, "_metrics_server_started", False)
    state = {"ok": False}
    port = _free_port()
    start_worker_metrics_server(port, ready=lambda: (state["ok"], "ok" if state["ok"] else "starting"))
    base = f"http://127.0.0.1:{port}"

    try:
        urllib.request.urlopen(f"{base}/health", timeout=5)
        raise AssertionError("an unready process answered 200")
    except urllib.error.HTTPError as exc:
        assert exc.code == 503 and exc.read() == b"starting"

    state["ok"] = True
    assert urllib.request.urlopen(f"{base}/health", timeout=5).status == 200
    assert b"worker_messages_received_total" in urllib.request.urlopen(f"{base}/metrics", timeout=5).read()
