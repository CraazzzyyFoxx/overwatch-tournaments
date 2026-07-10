"""Typed-RPC: manual recompute of impact-scoring baselines (superuser)."""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core.impact import FORMULA_VERSION
from src.core import db
from src.services.baselines import flows as baselines_flows

from . import _common as c

_SF = db.async_session_maker


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.parser.impact.recompute_baselines")
    async def _recompute(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_superuser(c.actor(data))
            rows = await baselines_flows.recompute(session)
            return {"rows": rows, "formula_version": FORMULA_VERSION}

        return await c.envelope(logger, "impact.recompute_baselines", op, session_factory=_SF)
