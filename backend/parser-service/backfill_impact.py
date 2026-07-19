"""CLI entrypoint for the idempotent MVP impact-scoring backfill (spec 2026-07-10).

Usage::

    cd backend/parser-service && uv run python backfill_impact.py [--tournament-id N]

Recomputes the 7 MVP-derived stats (event stats + ImpactPoints / ImpactRank /
OverperformanceScore) for every match that already has stat rows, using the
active baseline set. Safe to rerun — see
``src.services.match_logs.backfill`` for the idempotency contract.
"""

import argparse
import asyncio

from src.core import db
from src.core.caching import configure_cache
from src.services.match_logs.backfill import backfill_all


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill MVP impact-scoring stats for historical matches.")
    parser.add_argument(
        "--tournament-id",
        type=int,
        default=None,
        help="Only backfill matches belonging to this tournament (default: every tournament).",
    )
    return parser.parse_args()


async def _main(tournament_id: int | None) -> None:
    summary = await backfill_all(db.async_session_maker, tournament_id=tournament_id)
    print(summary)


if __name__ == "__main__":
    args = _parse_args()
    # The cashews `cache` singleton is process-global with no default backend
    # and this CLI reads baselines through it — must configure it before any
    # baseline read, exactly like serve.py does at worker startup (see
    # lesson_cashews_worker_not_configured).
    configure_cache()
    asyncio.run(_main(args.tournament_id))
