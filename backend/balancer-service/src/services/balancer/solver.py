from __future__ import annotations

import asyncio
from typing import Any

from src.services.balancer.algorithm.runtime import balance_teams_moo


async def run_balance(
    input_data: dict[str, Any],
    config_overrides: dict[str, Any] | None,
    progress_callback,
) -> dict[str, Any]:
    variants = await asyncio.to_thread(balance_teams_moo, input_data, config_overrides, progress_callback)
    return {"variants": variants}
