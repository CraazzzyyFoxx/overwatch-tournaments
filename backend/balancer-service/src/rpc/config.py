"""Public balancer config read over typed RPC.

``GET /api/balancer/config`` -> ``rpc.balancer.config`` (no auth). Validates the
payload through ``BalancerConfigResponse`` to mirror the HTTP ``response_model``
serialization exactly.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.schemas.rpc import rpc_error, rpc_ok
from src.schemas import BalancerConfigResponse
from src.services.balancer import jobs


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.config")
    async def _config(data: dict, msg: RabbitMessage) -> dict:
        try:
            payload = BalancerConfigResponse.model_validate(jobs.get_config())
            return rpc_ok(payload.model_dump(mode="json"))
        except Exception:  # pragma: no cover - defensive worker guard
            logger.exception("balancer rpc failed: config")
            return rpc_error("internal", "internal error")
