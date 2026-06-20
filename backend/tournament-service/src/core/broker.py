"""Process-global worker broker accessor for the headless tournament worker.

The HTTP service used a ``faststream.rabbit.fastapi.RabbitRouter`` that owned its
own broker (connected via the FastAPI lifespan); event publishers fell back to
``task_router.broker`` when no broker was threaded through. With the HTTP service
decommissioned the plain ``RabbitRouter`` has no broker, so the worker registers
its connected broker here once at startup. Publishers that aren't given an
explicit broker resolve it through ``require_broker`` instead — never silently
dropping a publish.
"""

from __future__ import annotations

from typing import Any

_worker_broker: Any | None = None


def set_worker_broker(broker: Any) -> None:
    """Register the worker's connected RabbitMQ broker (called from serve.py)."""
    global _worker_broker
    _worker_broker = broker


def require_broker(broker: Any | None = None) -> Any:
    """Return ``broker`` if given, else the registered worker broker.

    Raises a clear ``RuntimeError`` when neither is available so a misconfigured
    process fails loudly instead of silently swallowing the publish.
    """
    if broker is not None:
        return broker
    if _worker_broker is None:
        raise RuntimeError(
            "No RabbitMQ broker available: pass broker=... explicitly or call "
            "set_worker_broker(broker) at worker startup (serve.py)."
        )
    return _worker_broker
