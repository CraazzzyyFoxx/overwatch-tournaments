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

# The public config payload is derived purely from process constants (presets,
# defaults, limits), so validate + dump it once per process instead of on
# every request.
_config_payload: dict[str, Any] | None = None


def _get_config_payload() -> dict[str, Any]:
    global _config_payload
    if _config_payload is None:
        _config_payload = BalancerConfigResponse.model_validate(jobs.get_config()).model_dump(mode="json")
    return _config_payload


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.config")
    async def _config(data: dict, msg: RabbitMessage) -> dict:
        try:
            return rpc_ok(_get_config_payload())
        except Exception:  # pragma: no cover - defensive worker guard
            logger.exception("balancer rpc failed: config")
            return rpc_error("internal", "internal error")
