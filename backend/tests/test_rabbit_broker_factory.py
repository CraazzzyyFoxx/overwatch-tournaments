"""Tests for the shared RabbitBroker factory policy (deadline middleware + QoS)."""

from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

import pytest  # noqa: E402
from loguru import logger  # noqa: E402

from shared.observability import make_rabbit_broker  # noqa: E402
from shared.rpc.deadline import DeadlineDropMiddleware  # noqa: E402


def test_deadline_middleware_always_installed() -> None:
    broker = make_rabbit_broker("amqp://guest:guest@localhost:5672", logger=logger)
    assert DeadlineDropMiddleware in list(broker.config.broker_middlewares)


def test_extra_middlewares_are_kept() -> None:
    class Extra:  # noqa: B903 - sentinel only
        pass

    broker = make_rabbit_broker(
        "amqp://guest:guest@localhost:5672", logger=logger, middlewares=(Extra,)
    )
    mws = list(broker.config.broker_middlewares)
    assert DeadlineDropMiddleware in mws
    assert Extra in mws


def test_prefetch_passes_default_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeBroker:
        def __init__(self, url: str, **kwargs: object) -> None:
            captured["url"] = url
            captured.update(kwargs)

    import shared.observability.broker as broker_mod

    monkeypatch.setattr(broker_mod, "RabbitBroker", FakeBroker)
    broker_mod.make_rabbit_broker("amqp://x", logger=logger, prefetch_count=16)
    assert captured["default_channel"].prefetch_count == 16


def test_no_prefetch_means_no_default_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeBroker:
        def __init__(self, url: str, **kwargs: object) -> None:
            captured.update(kwargs)

    import shared.observability.broker as broker_mod

    monkeypatch.setattr(broker_mod, "RabbitBroker", FakeBroker)
    broker_mod.make_rabbit_broker("amqp://x", logger=logger)
    assert "default_channel" not in captured


def test_base_settings_expose_rpc_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared.core.config import BaseServiceSettings

    class S(BaseServiceSettings):
        postgres_user: str = "u"
        postgres_password: str = "p"
        postgres_db: str = "d"
        postgres_host: str = "h"
        postgres_port: str = "5432"

    assert S().rpc_prefetch_count == 16
    monkeypatch.setenv("RPC_PREFETCH_COUNT", "5")
    assert S().rpc_prefetch_count == 5
