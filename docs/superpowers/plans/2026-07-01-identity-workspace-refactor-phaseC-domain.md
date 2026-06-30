# Identity/Workspace Refactor — Phase C (Domain Migration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the workspace-isolated domain rows — `balancer.registration` (Part 4),
`tournament.player` (Part 5), and achievements (Part 6) — onto `workspace_member_id`, and
update the dependent backend queries and frontend reads.

**Architecture:** Each domain table gains a FK to `workspace.workspace_member.id`. Workspace
becomes derivable (`tournament_id → Tournament.workspace_id`) instead of denormalized.
Player-centric reads (public profiles, analytics, rank history) re-derive `player_id` via
`JOIN workspace_member ON workspace_member.id = <table>.workspace_member_id`.

**Tech Stack:** Python 3 (SQLAlchemy async, Alembic), Next.js 16 frontend. Depends on
**Phase B** (`workspace_member.player_id` must exist to backfill). Parts 4/5/6 are independent
of each other and may be done in parallel. Design spec:
`docs/superpowers/specs/2026-07-01-identity-workspace-refactor-design.md`.

## Global Constraints

- ORM in `backend/shared/models/`; migrations in `backend/migrations/versions/`, chained from
  Phase B's last migration (`iwrefac04`); set `down_revision` from `alembic heads` at execution.
- New `workspace_member_id` columns use `sa.BigInteger()` to match `workspace_member.id`
  (`db.TimeStampIntegerMixin` id is BigInteger); verify FK type compatibility on apply.
- Workspace is derived via `tournament_id → Tournament.workspace_id` (no denormalized copy).
- Player-centric reads MUST join back through `workspace_member` to `player_id` — do not assume
  `workspace_member_id == player_id`.
- Migrations: anak_dev only; round-trip each. TDD; commit per task; no push unless asked.
- Prefix git/test/build with `rtk`; edit files via Edit/Write only.

---

## Part 4 — `balancer.registration` on `workspace_member_id`

### Task 1: Model — add `workspace_member_id`, drop `auth_user_id` + `workspace_id`

**Files:**
- Modify: `backend/shared/models/balancer.py` (`BalancerRegistration`)
- Test: `backend/shared/tests/test_balancer_registration_member.py`

**Interfaces:**
- Produces: `BalancerRegistration.workspace_member_id: Mapped[int | None]` (FK
  `workspace.workspace_member.id` `ON DELETE SET NULL`, nullable, indexed) + `workspace_member`
  rel. Keeps `user_id`→players. Removes `auth_user_id`, `workspace_id`, their relationships.

- [ ] **Step 1: Write the failing test** — `workspace_member_id` present (nullable, FK to
  `workspace.workspace_member`); `auth_user_id`/`workspace_id` absent; `user_id` still present.

- [ ] **Step 2: Run → FAIL.**

Run: `cd backend && uv run --package shared pytest shared/tests/test_balancer_registration_member.py -v`

- [ ] **Step 3: Edit the model**

```python
workspace_member_id: Mapped[int | None] = mapped_column(
    ForeignKey("workspace.workspace_member.id", ondelete="SET NULL"),
    nullable=True, index=True,
)
workspace_member: Mapped["WorkspaceMember | None"] = relationship()
```
Remove `auth_user_id`, `workspace_id`, `auth_user`, `workspace` relationships. In
`__table_args__`, replace the `uq_balancer_registration_user` index's `auth_user_id` column
with `workspace_member_id` (keep the `WHERE deleted_at IS NULL` predicate); keep the other
indexes. Keep `reviewer`/`deleted_by_user`/`checked_in_by_user` (those stay on `auth.user`).

- [ ] **Step 4: Run → PASS. Step 5: Commit** `feat(balancer): registration anchored on workspace_member_id`.

---

### Task 2: Migration — backfill member, recreate unique index, drop old columns

**Files:**
- Create: `backend/migrations/versions/iwrefac05_registration_member.py` (`down_revision="iwrefac04"`)

- [ ] **Step 1: Write the migration**

```python
def upgrade() -> None:
    op.add_column("registration", sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
                  schema="balancer")
    op.execute(
        """
        UPDATE balancer.registration r
        SET workspace_member_id = wm.id
        FROM workspace.workspace_member wm
        JOIN players."user" pu ON pu.id = wm.player_id
        WHERE pu.auth_user_id = r.auth_user_id
          AND wm.workspace_id = r.workspace_id
        """
    )
    op.create_foreign_key("fk_registration_workspace_member", "registration",
                          "workspace_member", ["workspace_member_id"], ["id"],
                          source_schema="balancer", referent_schema="workspace",
                          ondelete="SET NULL")
    op.create_index("ix_balancer_registration_workspace_member_id", "registration",
                    ["workspace_member_id"], schema="balancer")
    # Recreate the active-registration uniqueness on the new anchor (correction #6).
    op.drop_index("uq_balancer_registration_user", table_name="registration", schema="balancer")
    op.create_index("uq_balancer_registration_user", "registration",
                    ["tournament_id", "workspace_member_id"], unique=True, schema="balancer",
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.drop_column("registration", "auth_user_id", schema="balancer")
    op.drop_column("registration", "workspace_id", schema="balancer")
```
Downgrade reverses (re-add columns, backfill `auth_user_id` via member→player→auth, restore the
old unique index).

> Sheet/CSV imports (no account) keep `workspace_member_id = NULL` — expected; the partial
> unique index treats multiple NULLs as distinct, matching today's behavior for tag-only rows.

- [ ] **Step 2: Apply + round-trip on anak_dev.**

- [ ] **Step 3: Verify** — no orphan member FK:
```sql
SELECT COUNT(*) FROM balancer.registration r
LEFT JOIN workspace.workspace_member wm ON wm.id = r.workspace_member_id
WHERE r.workspace_member_id IS NOT NULL AND wm.id IS NULL;  -- 0
```

- [ ] **Step 4: Commit** `feat(balancer): migrate registration to workspace_member_id`.

---

### Task 3: Update registration queries off `auth_user_id`/`workspace_id`

**Files:**
- Modify: `backend/shared/repository/registration.py` (`get_active_for_user`)
- Modify: `backend/tournament-service/src/services/registration/service.py` (`get_registration`, `create_registration`, history queries) + `.../registration/admin.py`
- Modify: `backend/tournament-service/src/rpc/registration_admin.py`, `.../rpc/public_rpc.py`
- Modify: `backend/tournament-service/src/core/auth.py`, `backend/balancer-service/src/core/auth.py`
- Modify: `backend/balancer-service/src/services/admin/balance_analytics.py`
- Test: extend the relevant service/RPC tests.

**Interfaces:**
- Consumes: Task 1/2. Produces: zero references to `BalancerRegistration.auth_user_id` /
  `BalancerRegistration.workspace_id`.

- [ ] **Step 1: Enumerate** — `grep -rn "registration.*auth_user_id\|BalancerRegistration.workspace_id\|\.workspace_id" backend` scoped to the files above; build a checklist.

- [ ] **Step 2: "my active registration"** (`get_active_for_user`, `get_registration`) — filter
  by member instead of auth_user:

```python
.where(
    models.BalancerRegistration.tournament_id == tournament_id,
    models.BalancerRegistration.workspace_member.has(
        models.WorkspaceMember.player.has(models.User.auth_user_id == auth_user_id)
    ),
    models.BalancerRegistration.deleted_at.is_(None),
)
```

- [ ] **Step 3: `create_registration`** — set `workspace_member_id` (from Phase B's
  `get_or_create_workspace_member`) instead of `auth_user_id`/`workspace_id`. Manual/sheet
  registrations pass `workspace_member_id=None`.

- [ ] **Step 4: workspace-derivation sites** — `_get_registration_workspace_id`
  (`balancer-service/core/auth.py`), `registration_admin.py` status-meta lookups, and
  `balance_analytics.py` derive workspace via `tournament_id → Tournament.workspace_id` (join)
  rather than `registration.workspace_id` / `balance.workspace_id`.

> `balance_analytics.py` uses `balance.workspace_id` (the `BalancerBalance` table, not
> registration) — confirm whether that column is in scope; if `BalancerBalance` retains its own
> `workspace_id`, leave it. Only registration's `workspace_id` is dropped here.

- [ ] **Step 5: `public_rpc.py` registration list** — drop the `registration.workspace_id ==`
  filter; scope by `tournament_id` (already workspace-bound) and `deleted_at IS NULL`.

- [ ] **Step 6: Run** tournament-service + balancer-service + shared suites → PASS (SKIP DB).

- [ ] **Step 7: Commit** `refactor(registration): queries via workspace_member; derive workspace from tournament`.

---

## Part 5 — `tournament.player` on `workspace_member_id`

### Task 4: Model — `user_id` → `workspace_member_id`

**Files:**
- Modify: `backend/shared/models/team.py` (`Player`)
- Test: `backend/shared/tests/test_tournament_player_member.py`

**Interfaces:**
- Produces: `Player.workspace_member_id: Mapped[int]` (FK `workspace.workspace_member.id`
  CASCADE, NOT NULL) + `workspace_member` rel; removes `user_id`/`user`. Indexes swapped to
  `ix_player_workspace_member_tournament`, `ix_player_team_workspace_member`, and the partial
  `is_substitution=false` variant on `(workspace_member_id, tournament_id)`.

- [ ] **Step 1: Write the failing test** — `workspace_member_id` present (NOT NULL, FK);
  `user_id` absent; the two member-keyed indexes exist.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Edit the model** — replace the `user_id` column/relationship with
  `workspace_member_id` (FK CASCADE, NOT NULL) + `workspace_member` rel; update `__table_args__`
  indexes (`ix_player_workspace_member_tournament` on `(workspace_member_id, tournament_id)`,
  `ix_player_team_workspace_member` on `(team_id, workspace_member_id)`, partial
  `ix_player_member_not_sub` on `(workspace_member_id, tournament_id) WHERE is_substitution=false`).

- [ ] **Step 4: Run → PASS. Step 5: Commit** `feat(tournament): Player anchored on workspace_member_id`.

---

### Task 5: Migration — backfill via `(workspace_id, player_id)`; swap indexes

**Files:**
- Create: `backend/migrations/versions/iwrefac06_player_member.py` (`down_revision="iwrefac05"`)

- [ ] **Step 1: Write the migration**

```python
def upgrade() -> None:
    op.add_column("player", sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
                  schema="tournament")
    op.execute(
        """
        UPDATE tournament.player tp
        SET workspace_member_id = wm.id
        FROM workspace.workspace_member wm
        JOIN tournament.tournament t ON t.id = tp.tournament_id
        WHERE wm.workspace_id = t.workspace_id
          AND wm.player_id = tp.user_id
        """
    )
    # Any roster player whose (workspace, player) has no member yet — create it (rosters can
    # include shadow players not yet enrolled via self-registration).
    op.execute(
        """
        INSERT INTO workspace.workspace_member (workspace_id, player_id, created_at)
        SELECT DISTINCT t.workspace_id, tp.user_id, now()
        FROM tournament.player tp
        JOIN tournament.tournament t ON t.id = tp.tournament_id
        LEFT JOIN workspace.workspace_member wm
          ON wm.workspace_id = t.workspace_id AND wm.player_id = tp.user_id
        WHERE wm.id IS NULL
        ON CONFLICT (workspace_id, player_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE tournament.player tp
        SET workspace_member_id = wm.id
        FROM workspace.workspace_member wm
        JOIN tournament.tournament t ON t.id = tp.tournament_id
        WHERE wm.workspace_id = t.workspace_id AND wm.player_id = tp.user_id
          AND tp.workspace_member_id IS NULL
        """
    )
    op.alter_column("player", "workspace_member_id", nullable=False, schema="tournament")
    op.create_foreign_key("fk_player_workspace_member", "player", "workspace_member",
                          ["workspace_member_id"], ["id"], source_schema="tournament",
                          referent_schema="workspace", ondelete="CASCADE")
    op.drop_index("ix_player_user_tournament", table_name="player", schema="tournament")
    op.drop_index("ix_player_team_user", table_name="player", schema="tournament")
    op.drop_index("ix_player_user_not_sub", table_name="player", schema="tournament")
    op.create_index("ix_player_workspace_member_tournament", "player",
                    ["workspace_member_id", "tournament_id"], schema="tournament")
    op.create_index("ix_player_team_workspace_member", "player",
                    ["team_id", "workspace_member_id"], schema="tournament")
    op.create_index("ix_player_member_not_sub", "player",
                    ["workspace_member_id", "tournament_id"], schema="tournament",
                    postgresql_where=sa.text("is_substitution = false"))
    op.drop_column("player", "user_id", schema="tournament")
```
Downgrade reverses (re-add `user_id`, backfill via member→player, restore old indexes).

> **Decision (correction #5/auto-enroll interaction):** the auto-`INSERT` of members for roster
> players means every historical roster entry becomes a workspace member. Confirm this is
> desired (it makes `workspace_member` the complete set of "players who appeared in this
> workspace"); if not, drop the auto-insert and require those members to pre-exist.

- [ ] **Step 2: Apply + round-trip on anak_dev.**

- [ ] **Step 3: Verify** — `SELECT COUNT(*) FROM tournament.player WHERE workspace_member_id IS NULL;` → 0.

- [ ] **Step 4: Commit** `feat(tournament): migrate player to workspace_member_id`.

---

### Task 6: Update `Player.user_id` readers

**Files:**
- Modify: every reader found by `grep -rn "Player.user_id\|\.user_id" backend` scoped to
  tournament-service / app-service / shared player queries (rosters, profiles, analytics).
- Test: extend the relevant suites.

**Interfaces:**
- Produces: zero references to `Player.user_id`. Player-centric reads join
  `Player.workspace_member → WorkspaceMember.player_id` (or filter
  `Player.workspace_member.has(WorkspaceMember.player_id == …)`).

- [ ] **Step 1: Enumerate** the readers; classify each as (a) "give me this player's rosters"
  (filter by member's `player_id`) or (b) "group rosters by player" (join to `player_id`).

- [ ] **Step 2: Rewrite** each. Example for `_get_player_workspace_id`
  (`tournament-service/core/auth.py`) — still resolvable via `tournament_id`, unchanged. For
  player-profile roster reads: `JOIN workspace_member ON workspace_member.id =
  player.workspace_member_id` then filter/group on `workspace_member.player_id`.

- [ ] **Step 3: Run** the suites → PASS (SKIP DB). **Step 4: Commit**
  `refactor(tournament): Player readers via workspace_member`.

---

## Part 6 — Achievements on `workspace_member_id`

### Task 7: Models — `AchievementEvaluationResult` + `AchievementOverride`

**Files:**
- Modify: `backend/shared/models/achievement.py`
- Test: `backend/shared/tests/test_achievement_member.py`

**Interfaces:**
- Produces: `AchievementEvaluationResult.workspace_member_id` and
  `AchievementOverride.workspace_member_id` (FK `workspace.workspace_member.id` CASCADE, NOT
  NULL) replacing `user_id`. Legacy `AchievementUser`/`Achievement` left untouched.

- [ ] **Step 1: Write the failing test** — both active models have `workspace_member_id` (FK to
  `workspace.workspace_member`), not `user_id`; the unique constraint on
  `AchievementEvaluationResult` uses `workspace_member_id` instead of `user_id`.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Edit the models** — swap `user_id` → `workspace_member_id` on both; update the
  `AchievementEvaluationResult` unique constraint
  (`achievement_rule_id, workspace_member_id, tournament_id, match_id`) and the `user`
  relationship → `workspace_member`. Keep `workspace_id`/`tournament_id`/`match_id`.

- [ ] **Step 4: Run → PASS. Step 5: Commit** `feat(achievements): results/overrides on workspace_member_id`.

---

### Task 8: Migration — backfill both tables via `(workspace_id, player_id)`

**Files:**
- Create: `backend/migrations/versions/iwrefac07_achievement_member.py` (`down_revision="iwrefac06"`)

- [ ] **Step 1: Write the migration** (same pattern for `evaluation_result` and `override`)

```python
def _migrate(table: str) -> None:
    op.add_column(table, sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
                  schema="achievements")
    op.execute(
        f"""
        UPDATE achievements.{table} a
        SET workspace_member_id = wm.id
        FROM workspace.workspace_member wm
        WHERE wm.player_id = a.user_id AND wm.workspace_id = a.workspace_id
        """
    )
    op.execute(
        f"""
        INSERT INTO workspace.workspace_member (workspace_id, player_id, created_at)
        SELECT DISTINCT a.workspace_id, a.user_id, now()
        FROM achievements.{table} a
        LEFT JOIN workspace.workspace_member wm
          ON wm.workspace_id = a.workspace_id AND wm.player_id = a.user_id
        WHERE wm.id IS NULL
        ON CONFLICT (workspace_id, player_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        UPDATE achievements.{table} a
        SET workspace_member_id = wm.id
        FROM workspace.workspace_member wm
        WHERE wm.player_id = a.user_id AND wm.workspace_id = a.workspace_id
          AND a.workspace_member_id IS NULL
        """
    )
    op.alter_column(table, "workspace_member_id", nullable=False, schema="achievements")
    op.create_foreign_key(f"fk_{table}_workspace_member", table, "workspace_member",
                          ["workspace_member_id"], ["id"], source_schema="achievements",
                          referent_schema="workspace", ondelete="CASCADE")
    op.drop_column(table, "user_id", schema="achievements")


def upgrade() -> None:
    _migrate("evaluation_result")
    _migrate("override")
```
Downgrade reverses for both. Update the `evaluation_result` unique constraint to the
`workspace_member_id` variant in the same migration (drop old, create new).

- [ ] **Step 2: Apply + round-trip on anak_dev. Step 3: Commit**
  `feat(achievements): migrate results/overrides to workspace_member_id`.

---

### Task 9: Update achievement readers + merge audit

**Files:**
- Modify: `backend/shared/services/achievement_effective.py` (`build_effective_achievement_rows_subquery`)
- Modify: `backend/app-service/src/services/achievements/service_v2.py` (count/paginate users)
- Modify: `backend/parser-service/src/services/achievement/engine/differ.py` (diff/insert)
- Modify: `backend/app-service/src/services/admin/user_merge.py` (REFERENCE_CONFIG)
- Test: extend the relevant suites.

**Interfaces:**
- Produces: effective-achievement reads keyed on `workspace_member_id`, then re-derived to
  `player_id` via `JOIN workspace_member` for player-facing grouping; `differ.py` writes
  `workspace_member_id`; merge audit routes through `workspace_member`.

- [ ] **Step 1: `achievement_effective.py`** — select `workspace_member_id` from
  `evaluation_result`/`override`, join `workspace_member` to expose `player_id`, and have
  the public-facing subquery group/return `player_id` (so profile/analytics stay player-centric).
  The revoke-override match stays on the same key (now `workspace_member_id`).

- [ ] **Step 2: `service_v2.py`** — `count(distinct …)` and pagination switch to the new key;
  if the UI lists *players* who earned a rule, group on the derived `player_id`.

- [ ] **Step 3: `differ.py`** — the engine knows the player (`players.user.id`) and the
  workspace (from the rule); resolve `workspace_member_id` via `get_or_create_workspace_member`
  (Phase B helper) before inserting `AchievementEvaluationResult`. Update the existing-results
  query to select `workspace_member_id`.

- [ ] **Step 4: `user_merge.py`** — replace the three `achievements.*.user_id` REFERENCE_CONFIG
  entries with logic that re-points the losing player's `workspace_member` rows (or merges the
  two members per workspace) — merging players now means merging their per-workspace members.

> `differ.py` runs in parser-service; confirm `get_or_create_workspace_member` is importable
> there (it lives in `shared/repository/workspace.py`) or inline the equivalent insert-or-select.

- [ ] **Step 5: Run** app-service + parser-service + shared achievement suites → PASS (SKIP DB).

- [ ] **Step 6: Commit** `refactor(achievements): readers + engine + merge on workspace_member`.

---

## Frontend + verification

### Task 10: Frontend reads touched by Parts 4–6

**Files:**
- Modify: registration lists, tournament rosters, achievement views (find with
  `grep -rn "auth_user_id\|user_id\|workspace_id" frontend/src/services frontend/src/components` scoped to registration/roster/achievement).
- Test: affected component tests (`bun test`).

- [ ] **Step 1: Audit** which FE reads consumed `registration.auth_user_id` /
  `registration.workspace_id` / `player.user_id` / `achievement.user_id` (most go through the
  gateway as opaque JSON; the contract is preserved where the API still returns `user_id`).

- [ ] **Step 2: Update** any field renames surfaced by the API changes; where the API keeps
  emitting `user_id`/`player_id` for display, no change is needed.

- [ ] **Step 3: Typecheck + lint** — `cd frontend && npx tsc --noEmit && npx eslint <changed>`.
  **Step 4: Component tests → PASS. Step 5: Commit** `feat(frontend): reads aligned to member anchor`.

### Task 11: End-to-end verification on anak_dev

**Files:** none (verification only).

- [ ] **Step 1:** Apply `iwrefac05`–`iwrefac07` on anak_dev (`DB_PGBOUNCER=false`).

- [ ] **Step 2: Run all four invariant queries** from the spec → all 0 rows.

- [ ] **Step 3:** Exercise the flows end-to-end: register (creates member + registration with
  `workspace_member_id`) → build teams (roster `Player.workspace_member_id` set) → run the
  achievement engine (writes `workspace_member_id`) → read the public profile (achievements,
  rosters, registrations all resolve by `player_id` via the member join).

- [ ] **Step 4: Cross-workspace check** — a player in two workspaces has two `workspace_member`
  rows; each workspace's reads return only its own member's data.

- [ ] **Step 5: Commit** any test/fixture additions made during verification.

---

## Self-Review

- **Spec coverage:** Part 4 — model (T1), migration + unique-index recreation (T2, correction
  #6), queries (T3); Part 5 — model (T4), migration (T5), readers (T6); Part 6 — models (T7),
  migration (T8), readers + merge (T9, correction #8); frontend (T10); E2E + invariants (T11).
- **Placeholder scan:** discovery points (`balance.workspace_id` scope, `differ.py` helper
  import, roster auto-enroll decision) name the exact file/decision — concrete, not "TBD".
- **Type consistency:** `workspace_member_id` (BigInteger, FK `workspace.workspace_member.id`)
  used identically across registration/player/achievements; player-centric reads always
  re-derive `player_id` via the member join (never assume `workspace_member_id == player_id`);
  `get_or_create_workspace_member` reused from Phase B.
- **Cross-phase dependency:** requires Phase B (`workspace_member.player_id`) before any T2/T5/T8 backfill.
