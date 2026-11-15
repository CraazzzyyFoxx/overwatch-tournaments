"""Merge every historical league's day tournaments into one tournament per season (spec §15).

Production runbook (run by the owner/controller from the release SHA; the merge is not an Alembic migration):

1. Make the composite FKs deferrable. Production must already be at ``flowP4_01`` or later (the P4 release note's deploy
   order); from an older revision this upgrade also runs the earlier flow migrations, which the running services
   cannot tolerate. The deployed services keep running::

       docker compose exec tournament-service sh -c "cd /app && alembic upgrade flowP6_01_deferrable_fks"

2. Propose the mapping, then fill every league's ``aggregate`` by hand (R3.Q5, spec §15.4)::

       docker compose exec tournament-service sh -c "cd /app && python -m scripts.league_merge plan --output league_merge.json"

3. Rehearse, then merge. ``apply`` writes ``league_merge.snapshot.json`` (the evaluation results of every affected
   member; an existing file is extended, never replaced) before the first league. Whatever leagues merged, even when a
   later one fails, it then queues one evaluation run per workspace, bumps the user-cache generation and queues one
   analytics job (skipped while the workspace has an active job: queue a ``compute`` job from the earliest target once
   that one finishes). Keep both files outside the container filesystem (a mounted path, or ``docker cp`` them out
   right after ``apply``); after a failure fix the cause, drop the merged leagues from the mapping and run ``apply``
   again::

       python -m scripts.league_merge apply --file league_merge.json --dry-run
       python -m scripts.league_merge apply --file league_merge.json

4. Wait until the queued evaluation runs (printed by ``apply``) are ``done``/``partial``, then grant every result the
   merge lost (idempotent; ``--granted-by`` is an ``auth.user`` id)::

       python -m scripts.league_merge grant --file league_merge.json --granted-by <auth user id>

5. Deploy normally: ``alembic upgrade head`` passes the ``flowP6_02`` guard once no league row remains.

Locally: ``cd backend/ && python -m scripts.league_merge …`` with the usual ``POSTGRES_*`` environment.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import click
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.services.cache_generations import bump, configure_generations
from shared.services.user_cache import COMPARE_GENERATIONS

# The merge calls the flow engine, which is tournament-service code.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tournament-service"))

from src.services.flow.league_merge import (  # noqa: E402  # ty: ignore[import-not-found]
    GrantSnapshot,
    MappingError,
    MergeError,
    affected_scope,
    apply_mapping,
    fetch_league_rows,
    grant_missing,
    load_mapping,
    plan_leagues,
    queue_analytics,
    queue_evaluations,
    snapshot_results,
)


def _session_maker() -> async_sessionmaker[AsyncSession]:
    # Lazy: building the engine needs the database environment, which a file check does not.
    from src.core.db import async_session_maker  # noqa: PLC0415  # ty: ignore[import-not-found]

    return async_session_maker


def _fail(message: str) -> NoReturn:
    click.echo(message)
    sys.exit(1)


def _snapshot_path(file: str) -> Path:
    return Path(file).with_suffix(".snapshot.json")


@click.group()
def cli() -> None:
    """League merge: plan, apply, grant."""


@cli.command()
@click.option("--output", default="league_merge.json", show_default=True, type=click.Path())
@click.option("--season-gap-days", default=21, show_default=True, type=int)
def plan(output: str, season_gap_days: int) -> None:
    """Propose the mapping file from the ``is_league`` tournaments (aggregates stay empty for the owner)."""
    if Path(output).exists():
        _fail(f"{output} already exists; move it away or pass another --output")

    async def run() -> list[dict[str, Any]]:
        async with _session_maker()() as session:
            return plan_leagues(await fetch_league_rows(session), season_gap_days=season_gap_days)

    planned = asyncio.run(run())
    Path(output).write_text(json.dumps(planned, indent=2, ensure_ascii=False), encoding="utf-8")
    days = sum(len(p["days"]) for p in planned)
    click.echo(f"{len(planned)} league seasons, {days} day tournaments -> {output}")


def _echo_log(entry: Any, log: Any) -> None:
    click.echo(f"{entry.league!r} season {entry.season} -> tournament {log.target_tournament_id}")
    click.echo(f"  deleted days: {log.deleted_tournament_ids}")
    for key, count in sorted(log.moved.items()):
        if count:
            click.echo(f"  moved {count:>5} {key}")
    for row in log.dropped:
        click.echo(f"  dropped {row.table} #{row.row_id} (day {row.tournament_id}) {row.key}")


@cli.command()
@click.option("--file", "file", default="league_merge.json", show_default=True, type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Run every merge and roll it back.")
def apply(file: str, dry_run: bool) -> None:
    """Merge every league of the file, then queue evaluation/analytics and bump the cache."""
    try:
        entries = load_mapping(Path(file).read_text(encoding="utf-8"))
    except MappingError as exc:
        _fail(str(exc))
    asyncio.run(_apply(file, entries, dry_run=dry_run))


async def _apply(file: str, entries: Sequence[Any], *, dry_run: bool) -> None:
    maker = _session_maker()
    if dry_run:
        for entry, log in zip(entries, await apply_mapping(maker, entries, dry_run=True), strict=True):
            _echo_log(entry, log)
        return
    target_of = {d.tournament_id: e.target_tournament_id for e in entries for d in e.days}
    async with maker() as session:
        workspaces, members = await affected_scope(session, target_of)
        snapshot = GrantSnapshot(await snapshot_results(session, member_ids=members, target_of=target_of))
    path = _snapshot_path(file)
    if path.exists():  # a re-run (after a failure or a dropped session) after a merge: never lose the first one's keys
        snapshot = snapshot.union(GrantSnapshot.from_json(path.read_text(encoding="utf-8")))
    path.write_text(snapshot.to_json(), encoding="utf-8")
    click.echo(f"snapshot of {len(snapshot.keys)} results -> {path}")
    committed: list[Any] = []
    try:
        await apply_mapping(maker, entries, dry_run=False, logs=committed)
    finally:
        # Whatever merged stays merged: its evaluations must run and the snapshot must name them, failure or not.
        if committed:
            await _after_merge(path, snapshot, entries, committed, workspaces)


async def _after_merge(
    path: Path, snapshot: GrantSnapshot, entries: Sequence[Any], logs: Sequence[Any], workspaces: set[int]
) -> None:
    async with _session_maker()() as session:
        run_ids = await queue_evaluations(session, workspaces)
        await session.commit()
    snapshot.run_ids = [*snapshot.run_ids, *run_ids]
    path.write_text(snapshot.to_json(), encoding="utf-8")

    from src.core.config import settings  # noqa: PLC0415  # ty: ignore[import-not-found]

    configure_generations(str(settings.redis_url))
    await bump(*COMPARE_GENERATIONS)
    for entry, log in zip(entries, logs, strict=False):
        _echo_log(entry, log)
    click.echo(f"evaluation runs: {snapshot.run_ids}")
    # Own transaction, after the evaluations: it can lose the race for the one running job per workspace.
    async with _session_maker()() as session:
        analytics = await queue_analytics(session, {e.target_tournament_id for e in entries[: len(logs)]})
        await session.commit()
    for workspace_id, outcome in analytics.items():
        click.echo(f"analytics workspace {workspace_id}: {outcome}")
    click.echo("run `grant` once these runs are done")


@cli.command()
@click.option("--file", "file", default="league_merge.json", show_default=True, type=click.Path())
@click.option("--granted-by", required=True, type=int, help="auth.user id recorded on the overrides")
def grant(file: str, granted_by: int) -> None:
    """Grant every result the merge lost, once the evaluation runs are finished."""
    path = _snapshot_path(file)
    if not path.exists():
        _fail(f"{path} does not exist; `apply` writes it")

    snapshot = GrantSnapshot.from_json(path.read_text(encoding="utf-8"))

    async def run() -> dict[int, int]:
        async with _session_maker()() as session:
            granted = await grant_missing(session, snapshot, granted_by=granted_by)
            await session.commit()
            return granted

    try:
        granted = asyncio.run(run())
    except MergeError as exc:
        _fail(str(exc))
    for rule, count in sorted(granted.items()):
        click.echo(f"rule {rule}: {count} grants")
    click.echo(f"{sum(granted.values())} grants in total")


if __name__ == "__main__":
    cli()
