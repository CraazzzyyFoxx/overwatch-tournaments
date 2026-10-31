"""CLI entrypoint for the idempotent MVP impact backfill (``impact_v2``).

Usage::

    cd backend/stats-service && uv run python backfill_impact.py [--tournament-id N]

Recomputes the kill-feed event stats and every ``impact_v2`` fact (impact points / rank, overperformance score and
badge, per-feature contributions) for every Overwatch match with player facts, using the active baseline set.
Replaces all non-character segments; preserves raw/character facts and audits each per-match commit. Safe to rerun.
Run it after ``rpc.stats.impact.recompute_baselines`` (design 2026-10-31 §8).
"""

import argparse
import asyncio

from shared.disciplines.overwatch.backfill import backfill_all
from src.core import db
from src.core.caching import configure_cache


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
    # baseline read, exactly like serve_worker.py does at startup (see
    # lesson_cashews_worker_not_configured).
    configure_cache()
    asyncio.run(_main(args.tournament_id))
