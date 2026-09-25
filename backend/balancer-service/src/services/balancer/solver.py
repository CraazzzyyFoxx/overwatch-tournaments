from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from shared.core.errors import BaseAPIException as HTTPException
from src.domain.balancer.result_serializer import lobby_document
from src.domain.balancer.runtime import balance_teams, balance_teams_tournament
from src.services.balancer.config.defaults import MAX_RESULT_VARIANTS

#: How many balance options one mix run hands back: the deepest pager the cap
#: allows. The brute-force mix engine has already enumerated every legal split
#: by the time it trims, so what a deeper pager costs is the stored document
#: every mix read ships, not the solve.
MIX_RESULT_VARIANTS = MAX_RESULT_VARIANTS


async def run_balance(
    input_data: dict[str, Any],
    config_overrides: dict[str, Any] | None,
    progress_callback,
    role_mask: dict[str, int] | None = None,
) -> dict[str, Any]:
    try:
        variants = await asyncio.to_thread(
            balance_teams_tournament,
            input_data,
            config_overrides,
            progress_callback,
            role_mask,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"variants": variants}


async def run_mix_balance(
    input_data: dict[str, Any],
    config_overrides: dict[str, Any] | None,
    progress_callback,
    role_mask: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Pickup-mix entry point: pins the mix_balancer backend.

    Mixes are always exactly 2 teams (see ``domain/balancer/backends/mix_balancer.py``),
    so this is the one call site allowed to request it; tournament balancing
    (``run_balance`` above) stays on ``tournament_balancer``.
    """
    # The mix engine enumerates every split exhaustively, so the extra options
    # cost only the trim at the end -- a host paging the matchup wants the deep
    # list, not the solver's top ten. A mix that stored its own override still
    # wins; the fallback below keeps the solver-wide default, because the GA
    # would have to actually *evolve* that many distinct archive entries.
    mix_overrides = {"max_result_variants": MIX_RESULT_VARIANTS, **(config_overrides or {})}
    try:
        variants = await asyncio.to_thread(
            balance_teams,
            input_data,
            mix_overrides,
            progress_callback,
            role_mask,
            algorithm="mix_balancer",
        )
    except RuntimeError as exc:
        if "mix_balancer requires" not in str(exc):
            raise
        # Linux-only compiled extension; missing in some images and on Windows.
        logger.warning("mix_balancer native engine unavailable; falling back to tournament_balancer")
        variants = await asyncio.to_thread(
            balance_teams,
            input_data,
            config_overrides,
            progress_callback,
            role_mask,
            algorithm="tournament_balancer",
        )
    # Stored on the mix and shipped with every read of it: each player once,
    # each option as seat ids (see ``lobby_document``).
    return lobby_document(variants)
