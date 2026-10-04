"""What one draft read costs: time, SQL statements, memory and Redis bytes.

Follow-up to the 2026-09-30 draft overload (``docs/incidents/2026-09-30``). The
shape is the incident's own: 26 teams, 130 seats (26 captains + 104 pool
players), 104 picks, every registration carrying roles, ranks, top heroes, an
identity and custom-field answers -- so the roster engine does the same work it
does in production.

Run it from ``backend/`` (one command, nothing to set up beyond Docker)::

    uv run python balancer-service/scripts/measure_draft_snapshot.py

It seeds the EPHEMERAL test Postgres (``docker-compose.test.yml``, 127.0.0.1:
55432/anak_test, started on demand by ``shared.testing``) and drops its own
rows afterwards. The DSN is pinned to that instance here, so a developer's
``.env`` cannot aim it at a real database.

Flags: ``--profile`` adds a cProfile of the cold snapshot load, ``--sql`` the
per-statement counts behind it, ``--picks`` the mid-draft states to measure.
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import io
import os
import pickle
import pstats
import sys
import time
import types
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SCRIPT_PATH = Path(__file__).resolve()
SERVICE_ROOT = SCRIPT_PATH.parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for candidate in (str(BACKEND_ROOT), str(SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.testing import apply_test_env_defaults  # noqa: E402
from shared.testing.db import EPHEMERAL_DB, EPHEMERAL_PORT  # noqa: E402

# Pinned BEFORE the defaults (process env wins over any .env): a developer's
# local .env may hold a real DSN, and this script writes ~1500 rows. It only
# ever runs against the throwaway docker-compose.test.yml instance, whose
# credentials are fixed.
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = EPHEMERAL_PORT
os.environ["POSTGRES_DB"] = EPHEMERAL_DB
os.environ["POSTGRES_USER"] = "postgres"
os.environ["POSTGRES_PASSWORD"] = "postgres"
apply_test_env_defaults()

import sqlalchemy as sa  # noqa: E402
from cashews import cache  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from shared.core.enums import DraftPickStatus, HeroClass  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.models.balancer.draft import DraftPick, DraftSession, DraftTeam  # noqa: E402
from shared.models.catalog.hero import Hero  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.platform.realtime import WorkspaceEvent  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistration,
    BalancerRegistrationForm,
    BalancerRegistrationFormVersion,
    BalancerRegistrationIdentity,
    BalancerRegistrationRole,
    BalancerRegistrationRoleHero,
)
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.testing import configure_test_cache, create_test_async_engine  # noqa: E402
from src import schemas  # noqa: E402
from src.domain.draft.entities import PoolSeat  # noqa: E402
from src.services.draft import feasibility as feasibility_mod  # noqa: E402
from src.services.draft import lifecycle, queue, selection  # noqa: E402
from src.services.draft.board import board_service  # noqa: E402
from src.services.draft.feasibility import feasibility_service  # noqa: E402

# The incident's draft: tournament 117, session 28.
TEAMS = 26
POOL_PLAYERS = 104
SHAPE = parse_roster_slots({"tank": 1, "damage": 2, "support": 2})
ROLES = ("tank", "damage", "support")
HERO_SLUGS = ("reinhardt", "winston", "tracer", "sojourn", "ana", "kiriko")
DEFAULT_PICK_STATES = (0, 52, 100)


# ---------------------------------------------------------------- instruments


class SqlCounter:
    """Counts statements on an engine, keyed by their first 60 characters."""

    def __init__(self, engine: Any) -> None:
        self.statements: Counter[str] = Counter()
        self.enabled = False
        event.listen(engine.sync_engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        if self.enabled:
            self.statements[" ".join(statement.split())[:60]] += 1

    @contextmanager
    def record(self):
        self.statements.clear()
        self.enabled = True
        try:
            yield self.statements
        finally:
            self.enabled = False

    @property
    def total(self) -> int:
        return sum(self.statements.values())


@dataclass
class Measurement:
    name: str
    ms: float
    sql: int
    bytes: int = 0


async def measure(
    counter: SqlCounter,
    name: str,
    call: Callable[[], Awaitable[Any]],
    *,
    repeats: int = 3,
) -> tuple[Measurement, Any]:
    """Best-of-``repeats`` wall time; the SQL count of the last run (they match)."""
    best = float("inf")
    result: Any = None
    statements: Counter[str] = Counter()
    for _ in range(repeats):
        await reset_caches()
        started = time.perf_counter()
        with counter.record() as seen:
            result = await call()
        best = min(best, (time.perf_counter() - started) * 1000.0)
        statements = Counter(seen)
    counter.statements = statements
    return Measurement(name, best, sum(statements.values())), result


async def reset_caches() -> None:
    """Every measurement here is a COLD one: nothing may be served from a cache."""
    feasibility_mod._read_snapshots.clear()
    await cache.clear()


def pickled_size(value: Any) -> int:
    """What cashews' Redis backend would store (it pickles the value)."""
    return len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


def retained_size(root: Any) -> int:
    """Bytes the object graph under ``root`` holds, each object counted once.

    Deterministic, unlike a ``tracemalloc`` delta: a read-snapshot entry is
    shared by every reader of one board state, so what matters is what it
    RETAINS -- the detached ORM rows and the resolved rosters hanging off it.
    """
    skip = (str, bytes, bytearray, int, float, bool, type(None), type, types.ModuleType, types.FunctionType)
    seen: set[int] = set()
    stack = [root]
    total = 0
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        total += sys.getsizeof(obj, 0)
        if isinstance(obj, skip):
            continue
        if isinstance(obj, dict):
            for key, value in obj.items():
                # A row's back-reference to its session, identity map and the
                # whole mapper registry is not what the snapshot costs.
                if key == "_sa_instance_state":
                    continue
                stack.append(key)
                stack.append(value)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        else:
            # ``__dict__`` through the type, not the instance: a mapped class'
            # registry proxy answers attribute lookups with a NameError.
            if "__dict__" in dir(type(obj)):
                stack.append(object.__getattribute__(obj, "__dict__"))
            slots = getattr(type(obj), "__slots__", ())
            for slot in (slots,) if isinstance(slots, str) else slots:
                try:
                    stack.append(object.__getattribute__(obj, slot))
                except AttributeError:
                    continue
    return total


# -------------------------------------------------------------------- fixture


@dataclass
class Fixture:
    workspace_id: int
    tournament_id: int
    user_ids: list[int]
    member_ids: list[int]
    draft_id: int


CUSTOM_FIELD_SCHEMA = {
    "schema_version": 1,
    "sections": [
        {
            "key": "accounts",
            "fields": [
                {"key": "battle_tag", "kind": "builtin", "required": True},
                {"key": "roles", "kind": "builtin"},
            ],
        },
        {
            "key": "about",
            "fields": [
                {"key": "discord_tag", "label": "Discord", "kind": "text", "visibility": "public"},
                {"key": "experience", "label": "Experience", "kind": "text", "visibility": "public"},
                {"key": "notes", "label": "Notes", "kind": "text", "visibility": "organizers"},
            ],
        },
    ],
}


async def _heroes(s: AsyncSession) -> list[int]:
    existing = dict((await s.execute(sa.select(Hero.slug, Hero.id).where(Hero.slug.in_(HERO_SLUGS)))).tuples().all())
    for slug in HERO_SLUGS:
        if slug in existing:
            continue
        hero = Hero(
            slug=slug,
            name=slug.title(),
            image_path=f"/heroes/{slug}.png",
            type=HeroClass.damage,
        )
        s.add(hero)
        await s.flush()
        existing[slug] = hero.id
    return [existing[slug] for slug in HERO_SLUGS]


async def seed(session_factory: async_sessionmaker[AsyncSession], suffix: str) -> Fixture:
    """The incident's draft, seeded and started, with no pick made yet."""
    async with session_factory() as s:
        ws = Workspace(slug=f"ws-{suffix}", name=f"WS {suffix}")
        s.add(ws)
        await s.flush()
        tourn = Tournament(workspace_id=ws.id, name=f"T {suffix}", slug=f"t-{suffix}", status="draft")
        tourn.roster_slots_json = {"tank": 1, "damage": 2, "support": 2}
        s.add(tourn)
        await s.flush()

        form = BalancerRegistrationForm(tournament_id=tourn.id, workspace_id=ws.id)
        s.add(form)
        await s.flush()
        version = BalancerRegistrationFormVersion(form_id=form.id, number=1, schema_json=CUSTOM_FIELD_SCHEMA)
        s.add(version)
        await s.flush()
        form.current_version_id = version.id

        hero_ids = await _heroes(s)
        total_seats = TEAMS + POOL_PLAYERS
        users = [User(name=f"p-{suffix}-{i}") for i in range(total_seats)]
        s.add_all(users)
        await s.flush()
        members = [WorkspaceMember(workspace_id=ws.id, player_id=u.id) for u in users]
        s.add_all(members)
        await s.flush()

        seats: list[PoolSeat] = []
        for i in range(total_seats):
            is_captain = i < TEAMS
            tag = f"P{suffix}-{i}#{1000 + i}"
            reg = BalancerRegistration(
                tournament_id=tourn.id,
                battle_tag=tag,
                battle_tag_normalized=tag.lower(),
                display_name=f"Player {i}",
                status="approved",
                balancer_status="ready",
                workspace_member_id=members[i].id,
                form_version_id=version.id,
                custom_fields_json={"discord_tag": f"player{i}", "experience": "2 seasons", "notes": "hidden"},
            )
            s.add(reg)
            await s.flush()
            # A real pool is mostly two- and three-role registrants; rotate the
            # lead role so the 26 teams can actually fill 1/2/2.
            lead = ROLES[i % 3]
            declared = [lead, *(role for role in ROLES if role != lead)][: 2 + (i % 2)]
            for priority, role in enumerate(declared):
                row = BalancerRegistrationRole(
                    registration_id=reg.id,
                    role=role,
                    is_primary=priority == 0,
                    priority=priority,
                    rank_value=2500 + (i * 37) % 2000 - priority * 150,
                    is_active=True,
                )
                s.add(row)
                await s.flush()
                for hero_priority in range(3):
                    s.add(
                        BalancerRegistrationRoleHero(
                            role_id=row.id,
                            hero_id=hero_ids[(i + hero_priority) % len(hero_ids)],
                            priority=hero_priority,
                        )
                    )
            s.add(
                BalancerRegistrationIdentity(
                    registration_id=reg.id,
                    provider="discord",
                    handle=f"player{i}",
                    handle_normalized=f"player{i}",
                )
            )
            seats.append(
                PoolSeat(registration_id=reg.id, draft_position=i + 1, team_name=f"Team {i + 1}")
                if is_captain
                else PoolSeat(registration_id=reg.id)
            )
        await s.flush()

        draft = await lifecycle.lifecycle_service.create_session(
            s, tournament_id=tourn.id, workspace_id=ws.id, shape=SHAPE
        )
        await lifecycle.lifecycle_service.seed(s, draft, seats=seats)
        await lifecycle.lifecycle_service.start(s, draft)
        await s.commit()
        return Fixture(
            workspace_id=ws.id,
            tournament_id=tourn.id,
            user_ids=[u.id for u in users],
            member_ids=[m.id for m in members],
            draft_id=draft.id,
        )


async def teardown(session_factory: async_sessionmaker[AsyncSession], fixture: Fixture) -> None:
    async with session_factory() as s:
        await s.execute(sa.delete(DraftSession).where(DraftSession.tournament_id == fixture.tournament_id))
        await s.execute(sa.delete(WorkspaceEvent).where(WorkspaceEvent.tournament_id == fixture.tournament_id))
        await s.execute(sa.delete(Tournament).where(Tournament.id == fixture.tournament_id))
        await s.execute(sa.delete(User).where(User.id.in_(fixture.user_ids)))
        await s.execute(sa.delete(Workspace).where(Workspace.id == fixture.workspace_id))
        await s.commit()


async def advance_to(session_factory: async_sessionmaker[AsyncSession], fixture: Fixture, picks_made: int) -> None:
    """Autopick until exactly ``picks_made`` picks are resolved."""
    async with session_factory() as s:
        draft = await s.get(DraftSession, fixture.draft_id)
        while True:
            done = await s.scalar(
                sa.select(sa.func.count())
                .select_from(DraftPick)
                .where(
                    DraftPick.session_id == draft.id,
                    DraftPick.status.in_((DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value)),
                )
            )
            if done >= picks_made or draft.current_pick_id is None:
                break
            await reset_caches()
            pick = await s.get(DraftPick, draft.current_pick_id)
            await selection.selection_service.autopick(s, draft, pick, expected_version=pick.version)
            await s.commit()
            await s.refresh(draft)


# ------------------------------------------------------------------ the table


async def measure_state(
    session_factory: async_sessionmaker[AsyncSession],
    counter: SqlCounter,
    fixture: Fixture,
    picks_made: int,
) -> tuple[list[Measurement], dict[str, int]]:
    async with session_factory() as s:
        draft = await s.get(DraftSession, fixture.draft_id)
        team = await s.scalar(
            sa.select(DraftTeam).where(DraftTeam.session_id == draft.id).order_by(DraftTeam.draft_position).limit(1)
        )

        rows: list[Measurement] = []

        snapshot_row, _ = await measure(counter, "load_snapshot (cold)", lambda: load_snapshot(s, draft))
        rows.append(snapshot_row)
        snapshot_sql = Counter(counter.statements)

        board_row, board = await measure(counter, "build_board (cold)", lambda: board_service.build_board(s, draft))
        board_row.bytes = pickled_size(board)
        rows.append(board_row)

        fit_row, fit = await measure(counter, "team_fit (1 team)", lambda: team_fit(s, draft, team.id))
        fit_row.bytes = pickled_size(fit)
        rows.append(fit_row)

        queue_row, queue_payload = await measure(
            counter, "queue_get (1 team)", lambda: queue.queue_service.read(s, draft, team)
        )
        queue_row.bytes = pickled_size(queue_payload)
        rows.append(queue_row)

        feas_row, feasibility = await measure(counter, "feasibility", lambda: analyze(s, draft))
        feas_row.bytes = pickled_size(feasibility)
        rows.append(feas_row)

        # What one shared in-process read-snapshot entry holds onto.
        await reset_caches()
        held = await feasibility_service.load_read_snapshot(s, draft)
        totals = {
            "read_snapshot_bytes": retained_size(held),
            "read_snapshot_players": len(held.players),
            "redis_state_bytes": board_row.bytes + feas_row.bytes + TEAMS * (fit_row.bytes + queue_row.bytes),
        }
        counter.statements = snapshot_sql
        return rows, totals


async def load_snapshot(s: AsyncSession, draft: DraftSession) -> Any:
    return await feasibility_service.load_snapshot(s, draft)


async def team_fit(s: AsyncSession, draft: DraftSession, team_id: int) -> schemas.DraftTeamFitResponse:
    scores = await feasibility_service.team_fit_scores(s, draft, team_id=team_id)
    return schemas.DraftTeamFitResponse(
        session_id=draft.id,
        team_id=team_id,
        scores=[schemas.DraftTeamFitScore.model_validate(score) for score in scores],
    )


async def analyze(s: AsyncSession, draft: DraftSession) -> schemas.DraftFeasibilityResponse:
    snapshot = await feasibility_service.load_read_snapshot(s, draft)
    state = await feasibility_service.state_from_snapshot(s, draft, snapshot)
    report = await feasibility_service.analyze_session(s, draft, state=state)
    return schemas.DraftFeasibilityResponse.model_validate(report)


def print_table(picks_made: int, rows: list[Measurement], totals: dict[str, int]) -> None:
    print(f"\n=== {TEAMS} teams / {TEAMS + POOL_PLAYERS} seats / {picks_made} picks made ===")
    print(f"{'read':<24}{'ms':>10}{'SQL':>7}{'payload KiB':>14}")
    print("-" * 55)
    for row in rows:
        payload = f"{row.bytes / 1024:.1f}" if row.bytes else "-"
        print(f"{row.name:<24}{row.ms:>10.1f}{row.sql:>7}{payload:>14}")
    print("-" * 55)
    print(f"{'read snapshot in memory':<24}{totals['read_snapshot_bytes'] / 1024:>10.1f} KiB")
    print(
        f"{'Redis per board state':<24}{totals['redis_state_bytes'] / 1024:>10.1f} KiB"
        f"  (board + feasibility + {TEAMS}x(fit+queue))"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picks", type=int, nargs="*", default=list(DEFAULT_PICK_STATES))
    parser.add_argument("--profile", action="store_true", help="cProfile the cold snapshot load")
    parser.add_argument("--sql", action="store_true", help="print the statements behind the cold snapshot load")
    args = parser.parse_args()

    configure_test_cache()
    engine = create_test_async_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    counter = SqlCounter(engine)
    suffix = f"draft-perf-{os.getpid()}"
    fixture = await seed(session_factory, suffix)
    try:
        for picks_made in sorted(args.picks):
            await advance_to(session_factory, fixture, picks_made)
            rows, totals = await measure_state(session_factory, counter, fixture, picks_made)
            print_table(picks_made, rows, totals)
            if args.sql:
                print("\n  SQL behind the cold snapshot load:")
                for statement, count in counter.statements.most_common():
                    print(f"  {count:>4}x {statement}")
            if args.profile:
                await profile_snapshot(session_factory, fixture)
    finally:
        await teardown(session_factory, fixture)
        await engine.dispose()
    return 0


async def profile_snapshot(session_factory: async_sessionmaker[AsyncSession], fixture: Fixture) -> None:
    """cProfile of the cold load, cumulative, top 25."""
    async with session_factory() as s:
        draft = await s.get(DraftSession, fixture.draft_id)
        await reset_caches()
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(5):
            await feasibility_service.load_snapshot(s, draft)
        profiler.disable()
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(25)
        print("\n  cProfile (5x cold load_snapshot):")
        print(stream.getvalue())


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
