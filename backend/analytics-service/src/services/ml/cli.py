"""``python -m src.services.ml.cli`` — command-line entry for v2 pipelines.

Subcommands:

- ``train --cutoff <tid>``        — train every active model kind.
- ``infer --tournament <tid>``    — run inference for one tournament.
- ``backfill --from N --to M``    — inference sweep over a range.
- ``backtest --window K``         — rolling backtest, rolled back afterwards; only its summary is attached to the
  active artifacts' metrics (``--no-persist`` skips that).
- ``evaluate [--from N] [--to M]`` — read-only: how well each shift method's levels predict the encounter outcomes
  of the next tournament (table, then JSON).

The tournament owns its discipline: ``--discipline`` is optional and rejected when it contradicts the tournament
named by ``--cutoff`` (train, backtest), ``--tournament`` (infer) or ``--from``/``--to`` (evaluate). ``backfill``
narrows the sweep to it; a ``backtest`` without ``--cutoff`` or an ``evaluate`` without bounds needs it to say which
game to score.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence

from src.core import db
from src.core.analytics_exports import tournament_discipline
from src.services.analytics.evaluate import evaluate_shift_methods, format_table

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
        await tournament_discipline(session, int(args.cutoff), explicit=args.discipline)
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
        await tournament_discipline(session, int(args.tournament), explicit=args.discipline)
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
            discipline=args.discipline,
        )
    print(json.dumps(summary, indent=2, default=str))
    return 0


async def _cmd_backtest(args: argparse.Namespace) -> int:
    from .training.backtest import backtest_service

    async with db.async_engine.connect() as connection:
        report = await backtest_service.run_rolling_backtest(
            connection,
            window=int(args.window),
            cutoff_tournament_id=int(args.cutoff) if args.cutoff else None,
            workspace_id=args.workspace_id,
            discipline=args.discipline,
        )
    if getattr(args, "persist", True):
        async with db.async_session_maker() as session:
            await backtest_service.persist_backtest_summary(session, report, discipline=report["discipline"])
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


async def _cmd_evaluate(args: argparse.Namespace) -> int:
    # Read-only: the session is never committed.
    async with db.async_session_maker() as session:
        report = await evaluate_shift_methods(
            session,
            discipline=args.discipline,
            workspace_id=args.workspace_id,
            from_tournament_id=args.from_id,
            to_tournament_id=args.to_id,
        )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    print(format_table(report))
    print(json.dumps(report, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analytics.ml.cli")
    parser.add_argument(
        "--workspace-id",
        type=int,
        default=None,
        help="Limit operations to a single workspace",
    )
    parser.add_argument(
        "--discipline",
        default=None,
        help="Game code; derived from the tournament, rejected when it contradicts it",
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

    p_eval = sub.add_parser("evaluate", help="Read-only shift-method evaluation on next-tournament encounters")
    p_eval.add_argument("--from", dest="from_id", type=int, default=None, help="First evaluated tournament_id")
    p_eval.add_argument("--to", dest="to_id", type=int, default=None, help="Last evaluated tournament_id")
    p_eval.add_argument("--output", default=None, help="Also write the JSON report to this file")

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
        "evaluate": _cmd_evaluate,
    }[args.cmd](args)
    return int(asyncio.run(coro) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
