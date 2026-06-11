from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

TARGET_PLAYER_COUNTS = (10, 20, 40, 60)
DEFAULT_REPEATS = 5

SCRIPT_PATH = Path(__file__).resolve()
SERVICE_ROOT = SCRIPT_PATH.parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent

for candidate in (str(BACKEND_ROOT), str(SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.services.balancer.algorithm.result_serializer import _build_response_payload  # noqa: E402
from src.services.balancer.algorithm.runtime import _prepare_balance_context  # noqa: E402
from src.services.balancer.algorithm.moo_backend import run_moo_optimizer  # noqa: E402


def _load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _slice_payload(payload: dict[str, Any], target_players: int) -> dict[str, Any]:
    players = payload.get("players")
    if not isinstance(players, dict):
        raise ValueError("Benchmark input must contain a top-level 'players' object")

    ordered_players = sorted(players.items())
    if len(ordered_players) < target_players:
        raise ValueError(f"Input payload contains only {len(ordered_players)} players, need {target_players}")

    sliced_players = dict(ordered_players[:target_players])
    sliced_payload = {"players": sliced_players}
    if "format" in payload:
        sliced_payload["format"] = payload["format"]
    return sliced_payload


def _run_single(payload: dict[str, Any], config_overrides: dict[str, Any] | None) -> dict[str, Any]:
    total_started_at = perf_counter()

    prepare_started_at = perf_counter()
    config, valid_players, num_teams, has_applied_overrides, role_assignment, optimizer_seed = _prepare_balance_context(
        payload,
        config_overrides,
        None,
    )
    prepare_ms = (perf_counter() - prepare_started_at) * 1000.0

    solve_started_at = perf_counter()
    pareto_solutions = run_moo_optimizer(
        valid_players,
        num_teams,
        config,
        None,
        role_assignment=role_assignment,
        seed=optimizer_seed,
    )
    solve_ms = (perf_counter() - solve_started_at) * 1000.0

    serialize_started_at = perf_counter()
    payloads = [
        _build_response_payload(
            result,
            valid_players,
            config.role_mask,
            config,
            has_applied_overrides,
            metrics,
        )
        for result, metrics in pareto_solutions
    ]
    serialize_ms = (perf_counter() - serialize_started_at) * 1000.0

    total_ms = (perf_counter() - total_started_at) * 1000.0
    return {
        "players": len(valid_players),
        "teams": num_teams,
        "variants": len(payloads),
        "prepare_ms": round(prepare_ms, 3),
        "solve_ms": round(solve_ms, 3),
        "serialize_ms": round(serialize_ms, 3),
        "redis_ms": 0.0,
        "total_ms": round(total_ms, 3),
    }


def _summarize_runs(player_count: int, runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        raise ValueError(f"No benchmark runs collected for {player_count} players")

    first_run = runs[0]
    return {
        "players": player_count,
        "players_used": first_run["players"],
        "teams": first_run["teams"],
        "variants": first_run["variants"],
        "repeats": len(runs),
        "prepare_ms": round(statistics.median(run["prepare_ms"] for run in runs), 3),
        "solve_ms": round(statistics.median(run["solve_ms"] for run in runs), 3),
        "serialize_ms": round(statistics.median(run["serialize_ms"] for run in runs), 3),
        "redis_ms": round(statistics.median(run["redis_ms"] for run in runs), 3),
        "total_ms": round(statistics.median(run["total_ms"] for run in runs), 3),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual balancer runtime benchmark for Linux + moo_core.")
    parser.add_argument(
        "--input",
        type=Path,
        default=SERVICE_ROOT / "teams.json",
        help="Path to an xv-1 style payload with a top-level players object.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="Number of runs per fixture size.",
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="*",
        default=list(TARGET_PLAYER_COUNTS),
        help="Player counts to benchmark. Each count should be divisible by the effective team size.",
    )
    parser.add_argument(
        "--config-json",
        type=str,
        default=None,
        help="Optional JSON string with balancer config overrides.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the raw benchmark summary as JSON.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    payload = _load_payload(args.input)
    config_overrides = json.loads(args.config_json) if args.config_json else None

    summaries: list[dict[str, Any]] = []
    for player_count in args.sizes:
        runs: list[dict[str, Any]] = []
        fixture_payload = _slice_payload(payload, player_count)
        for _ in range(args.repeats):
            runs.append(_run_single(fixture_payload, config_overrides))
        summaries.append(_summarize_runs(player_count, runs))

    print("players | teams | prepare_ms | solve_ms | serialize_ms | redis_ms | total_ms")
    for summary in summaries:
        print(
            f"{summary['players']:>7} | "
            f"{summary['teams']:>5} | "
            f"{summary['prepare_ms']:>10.3f} | "
            f"{summary['solve_ms']:>8.3f} | "
            f"{summary['serialize_ms']:>12.3f} | "
            f"{summary['redis_ms']:>8.3f} | "
            f"{summary['total_ms']:>8.3f}"
        )

    if args.output_json is not None:
        args.output_json.write_text(json.dumps(summaries, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
