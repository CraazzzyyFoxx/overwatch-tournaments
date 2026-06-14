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
from collections.abc import Sequence

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


async def _cmd_fit_weights(args: argparse.Namespace) -> int:
    """Offline, read-only: suggest a Linear shift scale aligned to the v2 merit scale.

    Computes Linear ``stable_shift`` at ``shift_scale=1`` and the v2 merit target
    (``shift_merit_scale · local_zscore``) for every player that has a Performance
    v2 row, then prints the scale that puts the two on the same division units.
    Set the result as ``LINEAR_SHIFT_SCALE`` and recompute v1 shifts to apply.
    """
    from src.core.config import settings
    from src.services.analytics import service as analytics_service
    from src.services.analytics.flows import compute_linear_metrics, get_data_frame
    from src.services.analytics.linear import suggest_shift_scale

    async with db.async_session_maker() as session:
        df = await get_data_frame(session, workspace_id=args.workspace_id)
        if df.empty:
            print(json.dumps({"error": "no analytics data"}))
            return 1
        df = compute_linear_metrics(df, shift_scale=1.0)
        perf = await analytics_service.get_performance_merit(session)

    merit_scale = settings.shift_merit_scale
    unit_shifts: list[float] = []
    merit_targets: list[float] = []
    for _, row in df.iterrows():
        zscore = perf.get(int(row["player_id"]))
        if zscore is None:
            continue
        unit_shifts.append(float(row["linear_stable_shift"]))
        merit_targets.append(merit_scale * float(zscore))

    suggested = suggest_shift_scale(unit_shifts, merit_targets, percentile=args.percentile)
    report = {
        "suggested_linear_shift_scale": round(suggested, 4),
        "current_linear_shift_scale": settings.linear_shift_scale,
        "shift_merit_scale": merit_scale,
        "alignment_percentile": args.percentile,
        "players_with_performance_v2": len(unit_shifts),
    }
    print(json.dumps(report, indent=2))
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

    p_fit = sub.add_parser(
        "fit-weights",
        help="Suggest a Linear shift scale aligned to the v2 merit scale (read-only)",
    )
    p_fit.add_argument(
        "--percentile",
        type=float,
        default=90.0,
        help="Percentile of |shift| matched between Linear and v2 merit (default 90)",
    )

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
        "fit-weights": _cmd_fit_weights,
    }[args.cmd](args)
    return int(asyncio.run(coro) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
