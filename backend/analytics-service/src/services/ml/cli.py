"""``python -m src.services.ml.cli`` — command-line entry for v2 pipelines.

Subcommands:

- ``train --cutoff <tid>``        — train every active model kind.
- ``infer --tournament <tid>``    — run inference for one tournament.
- ``backfill --from N --to M``    — inference sweep over a range.
- ``backtest --window K``         — Phase-6 rolling backtest.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Sequence

from src.core import db

from .inference.backfill import backfill_range
from .inference.runner import run_for_tournament
from .training.orchestrator import train_all_models

logger = logging.getLogger("analytics.ml.cli")


def _parse_model_kinds(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


async def _cmd_train(args: argparse.Namespace) -> int:
    async with db.async_session_maker() as session:
        summary = await train_all_models(
            session,
            cutoff_tournament_id=int(args.cutoff),
            model_kinds=_parse_model_kinds(args.models),
            workspace_id=args.workspace_id,
        )
        await session.commit()
    print(json.dumps(summary, indent=2, default=str))
    return 0


async def _cmd_infer(args: argparse.Namespace) -> int:
    async with db.async_session_maker() as session:
        summary = await run_for_tournament(
            session,
            int(args.tournament),
            workspace_id=args.workspace_id,
            model_kinds=_parse_model_kinds(args.models),
        )
    print(json.dumps(summary, indent=2))
    return 0


async def _cmd_backfill(args: argparse.Namespace) -> int:
    async with db.async_session_maker() as session:
        summary = await backfill_range(
            session,
            from_tournament_id=int(args.from_id),
            to_tournament_id=int(args.to_id),
            workspace_id=args.workspace_id,
            model_kinds=_parse_model_kinds(args.models),
        )
    print(json.dumps(summary, indent=2, default=str))
    return 0


async def _cmd_backtest(args: argparse.Namespace) -> int:
    # Phase 6 implementation wires this to training/backtest.py.
    from .training import backtest as bt

    async with db.async_session_maker() as session:
        report = await bt.run_rolling_backtest(
            session,
            window=int(args.window),
            cutoff_tournament_id=int(args.cutoff) if args.cutoff else None,
            workspace_id=args.workspace_id,
        )
        if getattr(args, "persist", True):
            await bt.persist_backtest_summary(session, report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analytics.ml.cli")
    parser.add_argument(
        "--workspace-id",
        type=int,
        default=None,
        help="Limit operations to a single workspace",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_train = sub.add_parser("train", help="Train v2 models up to a cutoff tournament")
    p_train.add_argument("--cutoff", required=True, help="Cutoff tournament_id")
    p_train.add_argument(
        "--models",
        default=None,
        help="Comma-separated model kinds (default: all active kinds)",
    )

    p_infer = sub.add_parser("infer", help="Run inference for one tournament")
    p_infer.add_argument("--tournament", required=True)
    p_infer.add_argument("--models", default=None)

    p_back = sub.add_parser("backfill", help="Sweep inference across a range")
    p_back.add_argument("--from", dest="from_id", required=True)
    p_back.add_argument("--to", dest="to_id", required=True)
    p_back.add_argument("--models", default=None)

    p_bt = sub.add_parser("backtest", help="Rolling-window backtest report")
    p_bt.add_argument("--window", type=int, default=5)
    p_bt.add_argument("--cutoff", default=None)
    p_bt.add_argument("--output", default=None)
    p_bt.add_argument(
        "--no-persist",
        dest="persist",
        action="store_false",
        default=True,
        help="Do not write the backtest summary into active artifact metrics",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    coro = {
        "train": _cmd_train,
        "infer": _cmd_infer,
        "backfill": _cmd_backfill,
        "backtest": _cmd_backtest,
    }[args.cmd](args)
    return int(asyncio.run(coro) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
