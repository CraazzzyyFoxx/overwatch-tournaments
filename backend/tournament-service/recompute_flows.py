"""CLI entrypoint for the post-deploy backfill of flow results (spec §14).

Usage::

    cd backend/tournament-service && uv run python recompute_flows.py [--tournament-id N]

Recomputes ``flow_node_result`` for every tournament that has a flow (or only the given one), one transaction per
tournament under the same row lock the standings job takes. Idempotent: a second run changes nothing. A tournament
that fails is reported and skipped; the exit code is non-zero if any did.
"""

import argparse
import asyncio
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.models.tournament.flow import FlowNode
from shared.repository import TournamentRepository
from src.core import db
from src.services.flow.engine import flow_engine

_tournaments = TournamentRepository()


async def recompute_all(
    session_maker: async_sessionmaker, *, tournament_id: int | None = None
) -> tuple[dict[int, int], dict[int, Exception]]:
    """``(tournament id -> number of changed nodes, tournament id -> error)``."""
    if tournament_id is not None:
        ids = [tournament_id]
    else:
        async with session_maker() as session:
            ids = list(
                await session.scalars(sa.select(FlowNode.tournament_id).distinct().order_by(FlowNode.tournament_id))
            )
    changed: dict[int, int] = {}
    failed: dict[int, Exception] = {}
    for tid in ids:
        try:
            async with session_maker() as session:
                await _tournaments.lock_for_computation(session, tid, skip_locked=False)
                report = await flow_engine.recompute(session, tid)
                await session.commit()
        except Exception as exc:
            failed[tid] = exc
        else:
            changed[tid] = len(report.changed_node_ids)
    return changed, failed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recompute flow results of tournaments that have a flow.")
    parser.add_argument(
        "--tournament-id", type=int, default=None, help="Only this tournament (default: every tournament with a flow)."
    )
    return parser.parse_args()


async def _main(tournament_id: int | None) -> int:
    changed, failed = await recompute_all(db.async_session_maker, tournament_id=tournament_id)
    for tid, n in changed.items():
        print(f"{tid}: {n} nodes changed")
    for tid, exc in failed.items():
        print(f"{tid}: failed: {exc!r}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_parse_args().tournament_id)))
