# Custom Games Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workspace-scoped custom (pickup) games that autobalance a hand-picked roster via the moo_core engine, plus a per-member "rank book" that supplies the ranks.

**Architecture:** Approach B — a first-class `CustomGame` entity (no `tournament_id`, no `BalancerBalance`, no tournament pollution) hosted in `balancer-service`, reusing only the pure `run_balance` engine. A separate, independently-shippable **Workspace Rank Book** (`(workspace, rater, player, role) → rank`) feeds the game's ranks through a resolution service (self / member / aggregate-median / OW-rank fallback).

**Tech Stack:** Python 3 (FastStream RabbitMQ RPC, SQLAlchemy async, Alembic), Rust `moo_core` (via `run_balance`), Go gateway (`edge.RouteSpec`-style routes), Next.js 16 + react-query + shadcn frontend.

## Global Constraints

- New ORM models live in `backend/shared/models/` (shared owns all models); migrations in `backend/migrations/versions/`. Services/RPC live in `backend/balancer-service`.
- New tables use the **`balancer`** Postgres schema (same as `BalancerBalance`).
- RPC handlers read the request **body from `data["payload"]`** (via `c.payload(data)`), path/query from the top level — never `data.get("<bodyfield>")`.
- Workspace RBAC: gate writes with `c.require_workspace_permission(data, user, workspace_id, "<resource>", "<action>")`; this already bypasses superusers. Gateway WS-ACL must decode `is_superuser` (already handled for balancer routes).
- Roles are `HeroClass` (`TANK`/`DAMAGE`/`SUPPORT`); SQLAlchemy `Enum` persists the member NAME. moo_core uses role keys `tank`/`dps`/`support` — map `DAMAGE→dps` at the engine boundary (reuse `services/balancer/algorithm/input_roles.py` / `team._resolve_hero_role`).
- Tests: `pytest` (backend), `bun test` + `npx tsc --noEmit` + `npx eslint` (frontend). Integration tests run against **anak_dev only** (never prod); they skip when the DB is unreachable.
- Migrations are NEVER run against prod. Set a migration's `down_revision` to the value reported by `alembic heads` on the working branch.
- Commit after each task. Do NOT push unless asked.

---

## Group A — Workspace Rank Book (independently shippable)

### Task 1: `WorkspacePlayerRank` model + migration

**Files:**
- Create: `backend/shared/models/custom_game.py`
- Modify: `backend/shared/models/__init__.py` (export new model)
- Create: `backend/migrations/versions/cgame0001_rank_book.py`
- Test: `backend/balancer-service/tests/test_rank_book_model.py`

**Interfaces:**
- Produces: `WorkspacePlayerRank(id, workspace_id, rater_user_id, player_user_id, role: HeroClass, rank_value: int, created_at, updated_at)`, table `balancer.workspace_player_rank`, unique on `(workspace_id, rater_user_id, player_user_id, role)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/balancer-service/tests/test_rank_book_model.py
from shared.models.custom_game import WorkspacePlayerRank
from shared.core.enums import HeroClass

def test_rank_model_table_and_columns():
    t = WorkspacePlayerRank.__table__
    assert t.schema == "balancer"
    assert t.name == "workspace_player_rank"
    cols = set(t.columns.keys())
    assert {"workspace_id", "rater_user_id", "player_user_id", "role", "rank_value"} <= cols
    uniques = [c for c in t.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({"workspace_id", "rater_user_id", "player_user_id", "role"}
               == {col.name for col in u.columns} for u in uniques)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --package balancer-service pytest balancer-service/tests/test_rank_book_model.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError: WorkspacePlayerRank`.

- [ ] **Step 3: Write the model** (follow `shared/models/social.py` conventions)

```python
# backend/shared/models/custom_game.py
from sqlalchemy import Enum as SAEnum, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db
from shared.core.enums import HeroClass

__all__ = ("WorkspacePlayerRank",)


class WorkspacePlayerRank(db.TimeStampIntegerMixin):
    """A single workspace member's subjective rank for a player in one role.

    `(workspace, rater, player, role)` is unique: each member maintains their own
    per-role opinion of each player. Consumed by custom-game balancing.
    """

    __tablename__ = "workspace_player_rank"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "rater_user_id", "player_user_id", "role",
            name="uq_workspace_player_rank",
        ),
        Index("ix_wpr_workspace_rater", "workspace_id", "rater_user_id"),
        Index("ix_wpr_workspace_player_role", "workspace_id", "player_user_id", "role"),
        {"schema": "balancer"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    rater_user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"))
    player_user_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    role: Mapped[HeroClass] = mapped_column(SAEnum(HeroClass))
    rank_value: Mapped[int] = mapped_column(Integer())
```

Add to `backend/shared/models/__init__.py` (mirror existing imports): `from shared.models.custom_game import *`.

> Verify `HeroClass` import path: `grep -rn "class HeroClass" backend/shared` and use that path in both the model and the test.

- [ ] **Step 4: Run model test to verify it passes**

Run: `cd backend && uv run --package balancer-service pytest balancer-service/tests/test_rank_book_model.py -v`
Expected: PASS.

- [ ] **Step 5: Write the migration**

```python
# backend/migrations/versions/cgame0001_rank_book.py
"""custom games phase 1: workspace_player_rank"""
import sqlalchemy as sa
from alembic import op

revision = "cgame0001"
down_revision = None  # set to the value from `alembic heads` on this branch
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_player_rank",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("rater_user_id", sa.BigInteger(), nullable=False),
        sa.Column("player_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("rank_value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rater_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "rater_user_id", "player_user_id", "role",
                            name="uq_workspace_player_rank"),
        schema="balancer",
    )
    op.create_index("ix_wpr_workspace_rater", "workspace_player_rank",
                    ["workspace_id", "rater_user_id"], schema="balancer")
    op.create_index("ix_wpr_workspace_player_role", "workspace_player_rank",
                    ["workspace_id", "player_user_id", "role"], schema="balancer")


def downgrade() -> None:
    op.drop_table("workspace_player_rank", schema="balancer")
```

> Confirm the `id` column type matches `db.TimeStampIntegerMixin` (BigInteger vs Integer) by reading `backend/shared/core/db.py`; match it exactly. Confirm the `role` column type matches how other Enum columns are stored in migrations (String length) — `grep -rn "Enum\|String(32)" backend/migrations/versions | head`.

- [ ] **Step 6: Apply + round-trip the migration on anak_dev**

Run (with anak_dev env, `DB_PGBOUNCER=false`): `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`.
Expected: table created, dropped, recreated with no error.

- [ ] **Step 7: Commit**

```bash
git add backend/shared/models/custom_game.py backend/shared/models/__init__.py backend/migrations/versions/cgame0001_rank_book.py backend/balancer-service/tests/test_rank_book_model.py
git commit -m "feat(custom-games): workspace_player_rank model + migration"
```

---

### Task 2: Rank resolution service (self / member / aggregate-median / OW fallback)

**Files:**
- Create: `backend/balancer-service/src/services/rank_book.py`
- Test: `backend/balancer-service/tests/test_rank_book_resolution.py`

**Interfaces:**
- Consumes: `WorkspacePlayerRank` (Task 1); the balancer's existing OW-rank resolver (find via `grep -rn "ow_rank\|overwatch_rank\|def.*rank" backend/balancer-service/src/services/balancer/algorithm/rating_normalizer.py backend/balancer-service/src/services/draft/ranks.py` and call the workspace-aware one).
- Produces:
  - `RankSource` = `Literal["self", "member", "aggregate"]`.
  - `async def resolve_rank(session, *, workspace_id: int, source: RankSource, source_user_id: int | None, player_user_id: int, role: HeroClass) -> int | None`
  - `async def resolve_ranks(session, *, workspace_id, source, source_user_id, players: list[tuple[int, HeroClass]]) -> dict[tuple[int, HeroClass], int | None]` (batched, no N+1)
  - `def _median(values: list[int]) -> int` (rounded to nearest int)

- [ ] **Step 1: Write the failing unit test for `_median`**

```python
# backend/balancer-service/tests/test_rank_book_resolution.py
from src.services.rank_book import _median

def test_median_odd():
    assert _median([4000, 4100, 4200]) == 4100

def test_median_even_rounds():
    assert _median([4000, 4100]) == 4050

def test_median_single():
    assert _median([3950]) == 3950
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run --package balancer-service pytest balancer-service/tests/test_rank_book_resolution.py -v`
Expected: FAIL — `ImportError: _median`.

- [ ] **Step 3: Implement `_median` + the resolution skeleton**

```python
# backend/balancer-service/src/services/rank_book.py
from __future__ import annotations

import statistics
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HeroClass
from shared.models.custom_game import WorkspacePlayerRank

RankSource = Literal["self", "member", "aggregate"]


def _median(values: list[int]) -> int:
    return round(statistics.median(values))


async def resolve_ranks(
    session: AsyncSession,
    *,
    workspace_id: int,
    source: RankSource,
    source_user_id: int | None,
    players: list[tuple[int, HeroClass]],
) -> dict[tuple[int, HeroClass], int | None]:
    """Resolve a per-(player, role) rank from the chosen source. Falls back to the
    player's imported OW rank, then None ("unrated")."""
    if not players:
        return {}
    player_ids = [p for p, _ in players]

    rows_q = sa.select(WorkspacePlayerRank).where(
        WorkspacePlayerRank.workspace_id == workspace_id,
        WorkspacePlayerRank.player_user_id.in_(player_ids),
    )
    if source in ("self", "member"):
        rows_q = rows_q.where(WorkspacePlayerRank.rater_user_id == source_user_id)
    rows = (await session.execute(rows_q)).scalars().all()

    if source == "aggregate":
        bucket: dict[tuple[int, HeroClass], list[int]] = {}
        for r in rows:
            bucket.setdefault((r.player_user_id, r.role), []).append(r.rank_value)
        book = {k: _median(v) for k, v in bucket.items()}
    else:
        book = {(r.player_user_id, r.role): r.rank_value for r in rows}

    out: dict[tuple[int, HeroClass], int | None] = {}
    missing: list[tuple[int, HeroClass]] = []
    for key in players:
        if key in book:
            out[key] = book[key]
        else:
            missing.append(key)
    if missing:
        ow = await _resolve_ow_ranks(session, workspace_id=workspace_id, players=missing)
        for key in missing:
            out[key] = ow.get(key)  # None when no OW rank either
    return out


async def resolve_rank(
    session: AsyncSession,
    *,
    workspace_id: int,
    source: RankSource,
    source_user_id: int | None,
    player_user_id: int,
    role: HeroClass,
) -> int | None:
    res = await resolve_ranks(
        session, workspace_id=workspace_id, source=source,
        source_user_id=source_user_id, players=[(player_user_id, role)],
    )
    return res[(player_user_id, role)]
```

- [ ] **Step 4: Implement `_resolve_ow_ranks`** by adapting the balancer's existing OW-rank resolver.

Read `backend/balancer-service/src/services/balancer/algorithm/rating_normalizer.py` and/or `services/draft/ranks.py` to find the function that maps a player (+role) to an OW-rank SR value within a workspace. Wrap it:

```python
async def _resolve_ow_ranks(
    session: AsyncSession, *, workspace_id: int, players: list[tuple[int, HeroClass]]
) -> dict[tuple[int, HeroClass], int | None]:
    # Delegate to the existing balancer OW-rank resolver; return None where unknown.
    # (Fill with the concrete call discovered above — same workspace-aware path the
    # tournament balancer uses for rank autofill.)
    ...
```

> This is the single discovery point in Group A: identify the exact existing resolver and call it. Do not invent a new OW-rank query — reuse the balancer's.

- [ ] **Step 5: Add resolution tests with a stubbed OW resolver + in-memory rows**

```python
import pytest
from shared.core.enums import HeroClass
from src.services import rank_book

@pytest.mark.asyncio
async def test_aggregate_uses_median(monkeypatch, async_session_with_ranks):
    # async_session_with_ranks: fixture seeding 3 raters' DAMAGE ranks 4000/4100/4200
    # for player 7 in workspace 1 (see conftest).
    monkeypatch.setattr(rank_book, "_resolve_ow_ranks", _no_ow)
    res = await rank_book.resolve_rank(
        async_session_with_ranks, workspace_id=1, source="aggregate",
        source_user_id=None, player_user_id=7, role=HeroClass.DAMAGE,
    )
    assert res == 4100

async def _no_ow(session, *, workspace_id, players):
    return {k: None for k in players}
```

(Add `self`/`member` and OW-fallback cases analogously. If a DB fixture is heavy, prefer the existing balancer test DB fixtures; otherwise gate these as anak_dev integration tests that skip when unreachable.)

- [ ] **Step 6: Run resolution tests**

Run: `cd backend && uv run --package balancer-service pytest balancer-service/tests/test_rank_book_resolution.py -v`
Expected: PASS (or SKIP for DB-backed cases when anak_dev is unreachable).

- [ ] **Step 7: Commit**

```bash
git add backend/balancer-service/src/services/rank_book.py backend/balancer-service/tests/test_rank_book_resolution.py
git commit -m "feat(custom-games): rank resolution (self/member/aggregate-median + OW fallback)"
```

---

### Task 3: RBAC permissions for rank book + custom game

**Files:**
- Modify: `backend/shared/rbac/catalog.py` (add to `PERMISSION_CATALOG`)
- Test: `backend/shared/tests/test_rbac_catalog_custom_games.py`

**Interfaces:**
- Produces catalog entries: `rank_book.read`, `rank_book.update`; `custom_game.{create,read,update,delete}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/shared/tests/test_rbac_catalog_custom_games.py
from shared.rbac.catalog import PERMISSION_CATALOG

def _names():
    return {(p.resource, p.action) for p in PERMISSION_CATALOG}

def test_custom_game_and_rank_book_permissions_present():
    n = _names()
    assert ("rank_book", "read") in n
    assert ("rank_book", "update") in n
    for action in ("create", "read", "update", "delete"):
        assert ("custom_game", action) in n
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run --package balancer-service pytest ../shared/tests/test_rbac_catalog_custom_games.py -v` (adjust path; or run from repo with the shared test runner used elsewhere).
Expected: FAIL.

- [ ] **Step 3: Add to the catalog** (mirror the `*_crud("balancer")` block)

```python
# in PERMISSION_CATALOG tuple, near the balancer entries:
    *_crud("custom_game"),
    _permission("rank_book", "read"),
    _permission("rank_book", "update"),
```

- [ ] **Step 4: Run to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/shared/rbac/catalog.py backend/shared/tests/test_rbac_catalog_custom_games.py
git commit -m "feat(custom-games): rank_book + custom_game RBAC permissions"
```

---

### Task 4: Rank book RPC subscribers

**Files:**
- Create: `backend/balancer-service/src/rpc/rank_book.py`
- Modify: `backend/balancer-service/serve.py` (register the module)
- Create: `backend/balancer-service/src/schemas/rank_book.py`
- Test: `backend/balancer-service/tests/test_rank_book_rpc.py`

**Interfaces:**
- Consumes: `rank_book.resolve_ranks` (Task 2), `c.payload/c.actor/c.require_workspace_permission` (from `src/rpc/_common.py`).
- Produces RPC topics:
  - `rpc.balancer.rankbook.list` — query `workspace_id`, `rater_user_id?` (default = self), returns `[{player_user_id, role, rank_value}]`.
  - `rpc.balancer.rankbook.set` — body `{workspace_id, player_user_id, role, rank_value}`, upsert into the caller's own book; returns the row.
  - `rpc.balancer.rankbook.bulk_set` — body `{workspace_id, items:[{player_user_id, role, rank_value}]}`, upsert many (caller's book); returns count.
  - `rpc.balancer.rankbook.delete` — body `{workspace_id, player_user_id, role}`, delete from caller's book.

- [ ] **Step 1: Write the failing RPC test** (mirror `tests` harness used by other balancer RPC tests — `grep -rn "def test_" backend/balancer-service/tests | head` to find the dispatch helper)

```python
# backend/balancer-service/tests/test_rank_book_rpc.py
# Dispatch rpc.balancer.rankbook.set as the caller (rater), then rpc.balancer.rankbook.list
# and assert the row round-trips and is scoped to the caller's rater_user_id.
# Use the same envelope/identity construction the other balancer RPC tests use.
```

(Write a concrete round-trip: `set` workspace=1 player=7 role=DAMAGE rank=4100 → `list` returns exactly that row for the caller.)

- [ ] **Step 2: Run to verify it fails** — FAIL (topic not registered).

- [ ] **Step 3: Implement subscribers** (mirror `src/rpc/config.py` + `_common.py` usage; enforce **own-book** writes by forcing `rater_user_id = actor.id`)

```python
# backend/balancer-service/src/rpc/rank_book.py
from __future__ import annotations
from typing import Any
import sqlalchemy as sa
from faststream.rabbit import RabbitMessage
from src.rpc import _common as c
from src.core.db import async_session_maker as _SF  # confirm name in src/core/db.py
from shared.models.custom_game import WorkspacePlayerRank
from shared.core.enums import HeroClass

def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.rankbook.set")
    async def _set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session):
            user = c.actor(data)
            body = c.payload(data)
            ws = int(body["workspace_id"])
            c.require_workspace_permission(data, user, ws, "rank_book", "update")
            row = WorkspacePlayerRank(
                workspace_id=ws, rater_user_id=user.id,
                player_user_id=int(body["player_user_id"]),
                role=HeroClass(body["role"]), rank_value=int(body["rank_value"]),
            )
            stmt = (
                sa.dialects.postgresql.insert(WorkspacePlayerRank.__table__)
                .values(workspace_id=row.workspace_id, rater_user_id=row.rater_user_id,
                        player_user_id=row.player_user_id, role=row.role.name,
                        rank_value=row.rank_value)
                .on_conflict_do_update(
                    constraint="uq_workspace_player_rank",
                    set_={"rank_value": row.rank_value},
                )
            )
            await session.execute(stmt)
            await session.commit()
            return {"workspace_id": ws, "player_user_id": row.player_user_id,
                    "role": row.role.name, "rank_value": row.rank_value}
        return await c.envelope(logger, "rankbook.set", op, session_factory=_SF)
    # ... list / bulk_set / delete mirror this shape; list reads with rater filter
    #     defaulting to actor.id, requires "rank_book","read".
```

> Confirm `c.envelope` exists in balancer `_common.py` (it mirrors app-service). If balancer uses a different envelope helper, match it. Confirm `async_session_maker` import path from `src/core/db.py`.

- [ ] **Step 4: Register in `serve.py`** — add `rank_book` to the list of RPC modules registered (mirror how `config`/`admin`/`draft` are registered).

- [ ] **Step 5: Run RPC test** — PASS (or SKIP if DB-backed and anak_dev unreachable).

- [ ] **Step 6: Commit**

```bash
git add backend/balancer-service/src/rpc/rank_book.py backend/balancer-service/src/schemas/rank_book.py backend/balancer-service/serve.py backend/balancer-service/tests/test_rank_book_rpc.py
git commit -m "feat(custom-games): rank book RPC (list/set/bulk_set/delete)"
```

---

### Task 5: Gateway routes for rank book

**Files:**
- Modify/Create: the balancer route table in `gateway/internal/balancer/*` (find with `grep -rn "rpc.balancer" gateway/internal | head`); add routes mirroring an existing balancer route entry.
- Test: `gateway` edge/route test (mirror existing) if present.

**Interfaces:**
- Produces gateway routes (`AuthRequired`, body under `payload`):
  - `GET  /api/v1/rank-book` → `rpc.balancer.rankbook.list`
  - `POST /api/v1/rank-book` → `rpc.balancer.rankbook.set` (Body)
  - `POST /api/v1/rank-book/bulk` → `rpc.balancer.rankbook.bulk_set` (Body)
  - `DELETE /api/v1/rank-book` → `rpc.balancer.rankbook.delete` (Body)

- [ ] **Step 1:** Locate the balancer route registration in the gateway (`grep -rn "rpc.balancer.config\|/api/balancer" gateway/`). Mirror one entry exactly (method, pattern, queue, Body, Auth).

- [ ] **Step 2:** Add the four routes above following that pattern.

- [ ] **Step 3: Build the gateway** — Run: `cd gateway && go build ./...` → Expected: exit 0.

- [ ] **Step 4: Run gateway tests** — Run: `cd gateway && go test ./internal/...` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/
git commit -m "feat(custom-games): gateway routes for /api/v1/rank-book"
```

---

### Task 6: Frontend — rank book service + grid

**Files:**
- Create: `frontend/src/services/rank-book.service.ts`
- Create: `frontend/src/app/.../rank-book/page.tsx` (place under the workspace/balancer section — mirror an existing balancer page location)
- Create: `frontend/src/components/rank-book/RankBookGrid.tsx`
- Test: `frontend/src/components/rank-book/RankBookGrid.test.ts(x)` (bun test)

**Interfaces:**
- Consumes: gateway `/api/v1/rank-book` (Task 5); `apiFetch`; `usePermissions`.
- Produces: `rankBookService.{list(workspaceId, raterUserId?), set(...), bulkSet(...), delete(...)}`.

- [ ] **Step 1:** Write `rank-book.service.ts` mirroring `me.service.ts`/`rbac.service.ts` (`apiFetch`, `res.json()`), typed `RankBookEntry = { player_user_id: number; role: HeroClass; rank_value: number }`.

- [ ] **Step 2:** Write `RankBookGrid` — rows = workspace players, columns = tank/damage/support, editable number cells (the caller's own book), debounced `bulkSet`. Reuse the balancer rank-row input component if one exists (`grep -rn "rank" frontend/src/components/balancer | head`).

- [ ] **Step 3:** Add the page; gate edit on `usePermissions` workspace `rank_book.update` (read open to members).

- [ ] **Step 4: Component test** — render the grid with a stub list, edit a cell, assert `bulkSet` called with the new value. Run: `cd frontend && bun test src/components/rank-book/`.

- [ ] **Step 5: Typecheck + lint** — Run: `cd frontend && npx tsc --noEmit && npx eslint src/services/rank-book.service.ts src/components/rank-book src/app/**/rank-book` → Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/rank-book.service.ts frontend/src/components/rank-book frontend/src/app/**/rank-book
git commit -m "feat(custom-games): rank book grid UI"
```

**Group A deliverable:** workspace members can set/view per-role player ranks. Independently usable.

---

## Group B — Custom Game (depends on Group A)

### Task 7: `CustomGame` + `CustomGamePlayer` models + migration

**Files:**
- Modify: `backend/shared/models/custom_game.py` (add two models + status enum)
- Modify: `backend/shared/models/__init__.py` (export)
- Create: `backend/migrations/versions/cgame0002_custom_game.py` (`down_revision = "cgame0001"`)
- Test: `backend/balancer-service/tests/test_custom_game_model.py`

**Interfaces:**
- Produces:
  - `CustomGameStatus` enum: `DRAFT`, `BALANCED`, `COMPLETED`, `CANCELLED`.
  - `CustomGame(id, workspace_id, name, status, config_json: dict, rank_source_type: str, rank_source_user_id: int|None, result_json: dict|None, outcome_json: dict|None, created_by: int|None, played_at, created_at, updated_at)`, table `balancer.custom_game`.
  - `CustomGamePlayer(id, custom_game_id, player_user_id, role: HeroClass, rank_value: int, team_index: int|None, sort_order: int)`, table `balancer.custom_game_player`, unique `(custom_game_id, player_user_id)`, relationship `custom_game.players`.

- [ ] **Step 1: Write the failing model test** (assert tables, schema, status enum members, unique constraint, `players` relationship). Mirror Task 1's test.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Add the models** to `custom_game.py`:

```python
import enum
from sqlalchemy import JSON, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship

class CustomGameStatus(str, enum.Enum):
    DRAFT = "draft"
    BALANCED = "balanced"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class CustomGame(db.TimeStampIntegerMixin):
    __tablename__ = "custom_game"
    __table_args__ = ({"schema": "balancer"},)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[CustomGameStatus] = mapped_column(SAEnum(CustomGameStatus), default=CustomGameStatus.DRAFT)
    config_json: Mapped[dict] = mapped_column(JSON, server_default="{}", default=dict)
    rank_source_type: Mapped[str] = mapped_column(String(16), server_default="self", default="self")
    rank_source_user_id: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    played_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    players: Mapped[list["CustomGamePlayer"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", passive_deletes=True)

class CustomGamePlayer(db.TimeStampIntegerMixin):
    __tablename__ = "custom_game_player"
    __table_args__ = (
        UniqueConstraint("custom_game_id", "player_user_id", name="uq_custom_game_player"),
        {"schema": "balancer"},
    )
    custom_game_id: Mapped[int] = mapped_column(ForeignKey("balancer.custom_game.id", ondelete="CASCADE"), index=True)
    player_user_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    role: Mapped[HeroClass] = mapped_column(SAEnum(HeroClass))
    rank_value: Mapped[int] = mapped_column(Integer())
    team_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", default=0)
    game: Mapped["CustomGame"] = relationship(back_populates="players")
```

Extend `__all__`. Update the migration `cgame0002` to create both tables (mirror Task 1's migration; `custom_game` first, then `custom_game_player` with FK to it).

- [ ] **Step 4: Run model test → PASS.**
- [ ] **Step 5: Apply + round-trip `cgame0002` on anak_dev.**
- [ ] **Step 6: Commit** `feat(custom-games): custom_game + custom_game_player models + migration`.

---

### Task 8: Custom game service — lifecycle + roster + rank seeding

**Files:**
- Create: `backend/balancer-service/src/services/custom_game.py`
- Test: `backend/balancer-service/tests/test_custom_game_service.py`

**Interfaces:**
- Consumes: `rank_book.resolve_ranks` (Task 2), models (Task 7).
- Produces:
  - `async def create_game(session, *, workspace_id, name, created_by, config=None) -> CustomGame`
  - `async def set_rank_source(session, *, game_id, source_type, source_user_id) -> CustomGame`
  - `async def update_roster(session, *, game, entries: list[{player_user_id, role}]) -> CustomGame` — replaces roster, seeds each `rank_value` via `resolve_ranks(source=game.rank_source_type, source_user_id=...)`, leaves seed `None` rows flagged unrated (rank_value defaults to 0 with an `unrated` marker in the response).
  - `async def set_rank(session, *, game_id, player_user_id, rank_value) -> CustomGamePlayer` (per-game override)
  - `async def record_outcome(session, *, game, outcome: dict) -> CustomGame` — validate `winner_team_index` in range, set status `COMPLETED`, set `played_at`.
  - status transition guard `def _assert_transition(game, target)`.

- [ ] **Step 1: Write failing tests** for: roster seeding pulls from the chosen source; per-game `set_rank` overrides without touching the rank book; `record_outcome` rejects an out-of-range winner; illegal transition (e.g. COMPLETED→balance) raises. Use anak_dev fixtures or stub `resolve_ranks`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the service per the interfaces (pure functions over the session; commit at the RPC layer, not here).
- [ ] **Step 4: Run → PASS** (SKIP DB cases when unreachable).
- [ ] **Step 5: Commit** `feat(custom-games): custom game lifecycle + roster + rank seeding`.

---

### Task 9: Balance integration (stateless moo_core)

**Files:**
- Create: `backend/balancer-service/src/services/custom_game_balance.py`
- Test: `backend/balancer-service/tests/test_custom_game_balance.py`

**Interfaces:**
- Consumes: `run_balance(input_data, config_overrides, progress_callback)` from `src/services/balancer/solver.py`; the input shape produced by `src/services/balancer/request_parser.py` / `player_loader.py` (read these to learn the exact `input_data` dict shape — players with role/rank).
- Produces:
  - `def build_input_data(game: CustomGame, players: list[CustomGamePlayer]) -> dict` — maps roster (player_user_id, role→`tank/dps/support`, rank_value) + `game.config_json` into the `input_data` shape.
  - `async def balance_game(session, *, game) -> CustomGame` — builds input, `await run_balance(input_data, game.config_json.get("overrides"), _noop_progress)`, takes `variants[0]`, writes `game.result_json` and per-player `team_index` from the variant's team assignment, sets status `BALANCED`.
  - `async def _noop_progress(*a, **k): pass` (or the no-op shape `progress_callback` expects — confirm from `jobs.py`).

- [ ] **Step 1:** Read `request_parser.py` + `runtime.balance_teams_moo` to capture the exact `input_data` schema and the `variants[0]` team/slot shape. Document the shape in a module docstring.
- [ ] **Step 2: Write failing test** — a fixed 10-player roster (2×5, ranks spread) → `balance_game` assigns every player a `team_index in {0,1}`, 5 per team, and `result_json` is non-empty with the `BalancerBalance.result_json` shape. Determinism: pass the engine's seed in `config_json` so the assignment is stable.
- [ ] **Step 3: Run → FAIL.**
- [ ] **Step 4: Implement** `build_input_data` + `balance_game` using `run_balance` (no `tournament_id`, no `BalancerBalance` write).
- [ ] **Step 5: Run → PASS.**
- [ ] **Step 6: Commit** `feat(custom-games): stateless moo_core balance for custom games`.

---

### Task 10: Custom game RPC subscribers

**Files:**
- Create: `backend/balancer-service/src/rpc/custom_game.py`
- Modify: `backend/balancer-service/serve.py`
- Create: `backend/balancer-service/src/schemas/custom_game.py` (read models for list/get/result)
- Test: `backend/balancer-service/tests/test_custom_game_rpc.py`

**Interfaces:**
- Consumes: Tasks 8 + 9 services; `c.require_workspace_permission(..., "custom_game", <action>)`.
- Produces topics: `rpc.balancer.custom.{create, list, get, update, update_roster, set_rank, set_rank_source, balance, move_player, record_outcome, delete}`. `create/update*/balance/record/delete` → `custom_game.<update|create|delete>` permission; `list/get` → `custom_game.read`. `move_player` updates one `team_index` (manual DnD tweak) and re-derives `result_json` team membership.

- [ ] **Step 1: Write failing RPC round-trip test** — `create` (ws=1) → `update_roster` (10 players) → `balance` → `get` shows teams → `record_outcome` → status `completed`. Mirror the balancer RPC test harness.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** subscribers (mirror `src/rpc/config.py` + Task 4; body via `c.payload`, id via `data["id"]`, commit in `op`).
- [ ] **Step 4: Register in `serve.py`.**
- [ ] **Step 5: Run → PASS** (SKIP when anak_dev unreachable).
- [ ] **Step 6: Commit** `feat(custom-games): custom game RPC surface`.

---

### Task 11: Gateway routes for custom games

**Files:** balancer route table in `gateway/internal/balancer/*` (mirror Task 5).

**Interfaces:** `AuthRequired`, workspace-scoped:
- `POST /api/v1/custom-games` → `rpc.balancer.custom.create` (Body)
- `GET /api/v1/custom-games` → `rpc.balancer.custom.list`
- `GET /api/v1/custom-games/{id}` → `rpc.balancer.custom.get` (IDParam)
- `PATCH /api/v1/custom-games/{id}` → `rpc.balancer.custom.update` (IDParam, Body)
- `PUT /api/v1/custom-games/{id}/roster` → `rpc.balancer.custom.update_roster` (IDParam, Body)
- `POST /api/v1/custom-games/{id}/rank` → `rpc.balancer.custom.set_rank` (IDParam, Body)
- `POST /api/v1/custom-games/{id}/rank-source` → `rpc.balancer.custom.set_rank_source` (IDParam, Body)
- `POST /api/v1/custom-games/{id}/balance` → `rpc.balancer.custom.balance` (IDParam)
- `POST /api/v1/custom-games/{id}/move` → `rpc.balancer.custom.move_player` (IDParam, Body)
- `POST /api/v1/custom-games/{id}/outcome` → `rpc.balancer.custom.record_outcome` (IDParam, Body)
- `DELETE /api/v1/custom-games/{id}` → `rpc.balancer.custom.delete` (IDParam, Success 204)

- [ ] **Step 1:** Add routes mirroring the existing balancer route pattern (and Task 5).
- [ ] **Step 2:** `cd gateway && go build ./...` → exit 0.
- [ ] **Step 3:** `cd gateway && go test ./internal/...` → PASS.
- [ ] **Step 4: Commit** `feat(custom-games): gateway routes for /api/v1/custom-games`.

---

### Task 12: Frontend — custom games service + list + editor

**Files:**
- Create: `frontend/src/services/custom-game.service.ts`
- Create: `frontend/src/app/.../custom-games/page.tsx` (list) + `.../custom-games/[id]/page.tsx` (editor)
- Create: `frontend/src/components/custom-game/CustomGameEditor.tsx` (+ subcomponents)
- Test: `frontend/src/components/custom-game/CustomGameEditor.test.tsx`

**Interfaces:**
- Consumes: gateway `/api/v1/custom-games/*` (Task 11), `rank-book.service` (Task 6) for the rank-source selector, balancer team-display + rank-row components (reuse — `grep -rn "Team\|Balance" frontend/src/components/balancer | head`).
- Produces: `customGameService.{create, list, get, update, updateRoster, setRank, setRankSource, balance, movePlayer, recordOutcome, delete}`.

- [ ] **Step 1:** `custom-game.service.ts` mirroring existing services (typed `CustomGame`, `CustomGamePlayer`, `CustomGameOutcome`).
- [ ] **Step 2:** Editor flow: roster picker (workspace players) → rank-source selector (self/member/aggregate) → per-player rank override → **Balance** → team-display (reuse balancer component) with DnD `move` → **Record outcome** (winner + per-map). react-query mutations; gate on `custom_game` perms via `usePermissions`.
- [ ] **Step 3:** List page (create + open). Public/SSR reads (if any) use the Next Data Cache tag + a `revalidate` server action mirroring `src/app/actions/users.ts`; the editor is client-side.
- [ ] **Step 4: Component test** — render editor with stub game, click Balance, assert `balance` mutation; record outcome, assert `recordOutcome` payload. Run: `cd frontend && bun test src/components/custom-game/`.
- [ ] **Step 5: Typecheck + lint** — `npx tsc --noEmit && npx eslint src/services/custom-game.service.ts src/components/custom-game src/app/**/custom-games` → clean.
- [ ] **Step 6: Commit** `feat(custom-games): custom games list + editor UI`.

---

### Task 13: End-to-end verification on anak_dev

**Files:** none (verification only).

- [ ] **Step 1:** Apply `cgame0001` + `cgame0002` on anak_dev (`DB_PGBOUNCER=false`).
- [ ] **Step 2:** Via RPC harness or running stack: set rank-book entries for a few players → create a custom game (source=self) → update roster (10 players) → verify ranks seeded from the book → balance → verify 2×5 teams → DnD move one player → record outcome → verify `completed` + `outcome_json`.
- [ ] **Step 3:** Repeat with `source=aggregate` (seed 3 raters) and assert the seeded rank equals the median.
- [ ] **Step 4:** Confirm NO `tournament`/`team`/`player`/`balancer.balance` rows were created by any custom-game operation.
- [ ] **Step 5: Commit** any test/fixture additions made during verification.

---

## Self-Review

- **Spec coverage:** Rank book model/service/RPC/gateway/UI (Tasks 1–6) ✔; selectable rank source self/member/aggregate-median + OW fallback (Task 2, 8) ✔; custom game model/lifecycle/roster/seeding (Tasks 7–8) ✔; stateless moo_core balance (Task 9) ✔; outcome winner+per-map (Tasks 8, 10) ✔; RPC + gateway `/api/v1/{rank-book,custom-games}` (Tasks 4,5,10,11) ✔; frontend (6,12) ✔; RBAC `custom_game`+`rank_book` per-workspace + superuser bypass (Task 3 + `require_workspace_permission`) ✔; no tournament pollution (Task 13 Step 4) ✔. Deferred items (logs/stats, OpenSkill rating, leaderboard, queue, realtime) are absent by design.
- **Discovery points (not placeholders — concrete reuse of named existing code):** OW-rank resolver (Task 2 Step 4), `input_data`/variant shape (Task 9 Step 1), balancer RPC test harness + `c.envelope`/`async_session_maker` names (Tasks 4,10), gateway balancer route entry to mirror (Task 5), reusable balancer FE components (Tasks 6,12). Each names the exact file to read.
- **Type consistency:** `RankSource`/`source_type` strings (`self|member|aggregate`) consistent across Tasks 2/7/8/10; `resolve_ranks` signature consistent between Task 2 (def) and Tasks 8/9 (use); `CustomGameStatus` values consistent; role keying (`HeroClass` stored as NAME, mapped to `tank/dps/support` only at the moo_core boundary) consistent across Tasks 1/7/9.
