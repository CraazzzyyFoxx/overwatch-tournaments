# Identity/Workspace Refactor — Phase A (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the `auth.user_player` M2M into a single nullable-unique
`players.user.auth_user_id` (provisioned at signup), and make `UserPermissionDeny`
workspace-scoped end-to-end. Both changes are additive and backward-compatible.

**Architecture:** `players.user` becomes the identity backbone with a 1:0..1 link to
`auth.user`. The per-user negative-RBAC deny gains an optional `workspace_id` that flows
through the existing deny pipeline (`_load_user_denies` → Redis/JWT → `set_rbac_cache` →
`is_denied`). The token/API contract is preserved (linked players emitted as a 0..1 array).

**Tech Stack:** Python 3 (SQLAlchemy async, Alembic, FastStream RPC), Next.js 16 frontend.
Design spec: `docs/superpowers/specs/2026-07-01-identity-workspace-refactor-design.md`.

## Global Constraints

- ORM models live in `backend/shared/models/`; migrations in `backend/migrations/versions/`.
- Alembic head on this branch is **`oauthmulti0001`** — set each new migration's
  `down_revision` from `alembic heads` at execution time; chain Phase-A migrations linearly.
- Mixin `db.TimeStampIntegerMixin` gives `id` (**BigInteger**), `created_at`, `updated_at`.
  FK columns to `auth.user.id` / `players.user.id` follow existing migrations (`sa.Integer()`
  is used for those FKs today — match the column already present when adding/altering).
- `UserPermissionDeny`'s real column is **`user_id`** (FK `auth.user.id`), not `auth_user_id`.
- Deny dict shape is `{resource, action}` today; after this phase `{resource, action,
  workspace_id}`. A dict missing `workspace_id` (old JWT/cache) = **global** deny.
- Migrations run **anak_dev only** (`DB_PGBOUNCER=false`), never prod; round-trip each
  (`alembic upgrade head` → `downgrade -1` → `upgrade head`).
- TDD: failing test → minimal impl → green. Commit after each task. Do NOT push unless asked.
- Prefix git/test/build with `rtk`. Edit files via Edit/Write only (PowerShell mangles UTF-8).
- Run backend tests with `cd backend && uv run --package <service> pytest <path> -v`.

---

## Part 1 — Collapse `auth.user_player`

### Task 1: `players.User.auth_user_id` column + `AuthUser.player` relationship

**Files:**
- Modify: `backend/shared/models/user.py`
- Modify: `backend/shared/models/auth_user.py`
- Test: `backend/shared/tests/test_user_auth_link_model.py`

**Interfaces:**
- Produces: `User.auth_user_id: Mapped[int | None]` (FK `auth.user.id` `ON DELETE SET NULL`,
  unique, indexed); `User.auth_user` rel; `AuthUser.player: Mapped["User | None"]`
  (`uselist=False`, `back_populates="auth_user"`). `AuthUser.player_links` stays until Task 6.

- [ ] **Step 1: Write the failing test**

```python
# backend/shared/tests/test_user_auth_link_model.py
from shared.models.user import User
from shared.models.auth_user import AuthUser

def test_user_has_unique_nullable_auth_user_id():
    col = User.__table__.columns["auth_user_id"]
    assert col.nullable is True
    assert col.unique is True
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.schema == "auth"
    assert fk.column.table.name == "user"

def test_authuser_player_relationship_is_scalar():
    rel = AuthUser.__mapper__.relationships["player"]
    assert rel.uselist is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run --package shared pytest shared/tests/test_user_auth_link_model.py -v`
Expected: FAIL — `KeyError: 'auth_user_id'` / `KeyError: 'player'`.

- [ ] **Step 3: Add the column + relationships**

In `backend/shared/models/user.py`, add to `User` (mirror existing `mapped_column` style):

```python
auth_user_id: Mapped[int | None] = mapped_column(
    ForeignKey("auth.user.id", ondelete="SET NULL"),
    nullable=True, unique=True, index=True,
)
auth_user: Mapped["AuthUser | None"] = relationship(back_populates="player")
```

Add the `ForeignKey`/`relationship` imports if missing, and a `TYPE_CHECKING` import of
`AuthUser`. In `backend/shared/models/auth_user.py`, add to `AuthUser`:

```python
player: Mapped["User | None"] = relationship(
    back_populates="auth_user", uselist=False, viewonly=False,
)
```

> Confirm there is no import cycle: `User` and `AuthUser` are in sibling modules already
> imported by `shared/models/__init__.py`; use string targets in `relationship`/`ForeignKey`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run --package shared pytest shared/tests/test_user_auth_link_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/shared/models/user.py backend/shared/models/auth_user.py backend/shared/tests/test_user_auth_link_model.py
rtk git commit -m "feat(identity): players.user.auth_user_id + AuthUser.player 1:0..1"
```

---

### Task 2: Migration — add `auth_user_id`, backfill from `is_primary`, unique index

**Files:**
- Create: `backend/migrations/versions/iwrefac01_user_auth_link.py`
- Test: round-trip on anak_dev (Step 5).

**Interfaces:**
- Produces: column `players.user.auth_user_id` + partial unique index
  `uq_players_user_auth_user_id` (`WHERE auth_user_id IS NOT NULL`).

- [ ] **Step 1: Pre-migration audit (decision gate — correction #5)**

Run on anak_dev:
```sql
SELECT auth_user_id, COUNT(*) FROM auth.user_player GROUP BY auth_user_id HAVING COUNT(*) > 1;
```
If any rows: surface the list to the user. The migration backfills **only the `is_primary`
link**; the non-primary players stay shadow (`auth_user_id IS NULL`). Record the decision in
the PR description.

- [ ] **Step 2: Write the migration**

```python
# backend/migrations/versions/iwrefac01_user_auth_link.py
"""identity refactor: players.user.auth_user_id (collapse auth.user_player)"""
import sqlalchemy as sa
from alembic import op

revision = "iwrefac01"
down_revision = "oauthmulti0001"  # confirm via `alembic heads`
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("auth_user_id", sa.Integer(), nullable=True),
        schema="players",
    )
    op.create_foreign_key(
        "fk_players_user_auth_user", "user", "user",
        ["auth_user_id"], ["id"],
        source_schema="players", referent_schema="auth", ondelete="SET NULL",
    )
    # Backfill from the PRIMARY link only (one auth_user -> at most one player).
    op.execute(
        """
        UPDATE players."user" pu
        SET auth_user_id = up.auth_user_id
        FROM auth.user_player up
        WHERE up.player_id = pu.id AND up.is_primary = true
        """
    )
    op.create_index(
        "uq_players_user_auth_user_id", "user", ["auth_user_id"],
        unique=True, schema="players",
        postgresql_where=sa.text("auth_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_players_user_auth_user_id", table_name="user", schema="players")
    op.drop_constraint("fk_players_user_auth_user", "user", schema="players", type_="foreignkey")
    op.drop_column("user", "auth_user_id", schema="players")
```

> Confirm the FK column type: existing FKs to `auth.user.id` use `sa.Integer()` in current
> migrations even though ids are BigInteger — match that (`grep -rn "auth.user.id" backend/migrations/versions | head`).

- [ ] **Step 3: Apply + round-trip on anak_dev**

Run (anak_dev env, `DB_PGBOUNCER=false`): `alembic upgrade head` → `alembic downgrade -1`
→ `alembic upgrade head`. Expected: no error.

- [ ] **Step 4: Verify the bijection invariant**

```sql
SELECT auth_user_id, COUNT(*) FROM players."user"
WHERE auth_user_id IS NOT NULL GROUP BY auth_user_id HAVING COUNT(*) > 1;  -- 0 rows
```

- [ ] **Step 5: Commit**

```bash
rtk git add backend/migrations/versions/iwrefac01_user_auth_link.py
rtk git commit -m "feat(identity): migration add players.user.auth_user_id + primary backfill"
```

---

### Task 3: Provision `players.User` at signup (password + OAuth)

**Files:**
- Modify: `backend/identity-service/src/services/auth_service.py` (`create_user`)
- Modify: `backend/identity-service/src/services/oauth_flows.py` (callback) and/or the
  `OAuthService.handle_callback` it calls (find the AuthUser-creation site).
- Test: `backend/identity-service/tests/test_signup_provisions_player.py`

**Interfaces:**
- Produces: a helper `ensure_player_for_auth_user(session, auth_user) -> User` (idempotent:
  returns the existing linked player or creates `User(name=<username or email>, auth_user_id=auth_user.id)`).
  Place it in `backend/identity-service/src/services/player_link_service.py` (reused by Task 4).

- [ ] **Step 1: Write the failing test** (register a user → a `players.user` exists with
  `auth_user_id == new auth_user.id` and `name == username`).

```python
# backend/identity-service/tests/test_signup_provisions_player.py
# Use the same async DB fixture other identity-service tests use (grep tests/conftest.py).
# 1) call auth_flows.register(session, UserRegister(...))
# 2) assert select(User).where(User.auth_user_id == user.id) returns one row.
# Skip when anak_dev unreachable (mirror existing DB-test skip).
```

- [ ] **Step 2: Run → FAIL** (no player created).

- [ ] **Step 3: Implement the helper + wire both signup paths**

```python
# player_link_service.py
async def ensure_player_for_auth_user(session, auth_user) -> "User":
    existing = await session.scalar(
        sa.select(User).where(User.auth_user_id == auth_user.id)
    )
    if existing is not None:
        return existing
    player = User(name=auth_user.username or auth_user.email, auth_user_id=auth_user.id)
    session.add(player)
    await session.flush()
    return player
```

Call it in `auth_service.create_user` after `session.flush()` (before the final commit), and
in the OAuth account-creation branch where a brand-new `AuthUser` is created. Idempotency
guards the OAuth "existing user logs in again" path.

> Find the OAuth AuthUser creation site: `grep -rn "AuthUser(" backend/identity-service/src`.
> Provision only when a NEW auth_user is created, not on every login.

- [ ] **Step 4: Run → PASS** (or SKIP when anak_dev unreachable).

- [ ] **Step 5: Commit**

```bash
rtk git add backend/identity-service/src/services/auth_service.py backend/identity-service/src/services/oauth_flows.py backend/identity-service/src/services/player_link_service.py backend/identity-service/tests/test_signup_provisions_player.py
rtk git commit -m "feat(identity): provision players.user at signup (password + oauth)"
```

---

### Task 4: `PlayerLinkService.link/unlink` → `players.user.auth_user_id`

**Files:**
- Modify: `backend/identity-service/src/services/player_link_service.py`
- Test: `backend/identity-service/tests/test_player_link_service.py` (extend/replace existing)

**Interfaces:**
- Consumes: Task 1 column. Produces: `link_player` sets `players.user.auth_user_id = auth_user.id`
  (rejecting if the player is already linked to a different account); `unlink_player` sets it to
  `NULL`; `get_linked_players` returns the 0-or-1 linked player.

- [ ] **Step 1: Write failing tests** — link sets `auth_user_id`; double-link to another account
  raises 409; unlink nulls it; `get_linked_players` returns `[player]` then `[]` after unlink.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Reimplement** the link/unlink/get methods as `UPDATE players.user` over the
  new column (drop the `AuthUserPlayer` insert/delete + `is_primary` bookkeeping). Keep the
  ownership verification (Discord/Battle.net OAuth match) that gates `link_player`.

```python
async def _link_player_to_auth_user(session, auth_user_id: int, player_id: int) -> None:
    player = await session.get(User, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    if player.auth_user_id is not None and player.auth_user_id != auth_user_id:
        raise HTTPException(status_code=409, detail="Player is already linked to another account")
    player.auth_user_id = auth_user_id
    await session.flush()
```

- [ ] **Step 4: Run → PASS** (SKIP DB cases when unreachable).

- [ ] **Step 5: Commit** `refactor(identity): PlayerLinkService over players.user.auth_user_id`.

---

### Task 5: Replace remaining `AuthUserPlayer` usages + reconcile `ensure_player_identity`

**Files:**
- Modify: `backend/identity-service/src/services/auth_token_helpers.py` (`_linked_players_payload`)
- Modify: `backend/identity-service/src/schemas/auth.py` (`AuthLinkedPlayer` source)
- Modify: `backend/tournament-service/src/rpc/public_rpc.py` (lines ~369, ~397)
- Modify: `backend/app-service/src/services/admin/user_merge.py` (drop `auth.user_player` ref)
- Modify: `backend/app-service/src/services/workspace/service.py` (any `AuthUserPlayer` use)
- Modify: `backend/shared/rbac/bootstrap.py`, `backend/shared/rpc/identity.py` (if referenced)
- Modify: `backend/tournament-service/src/services/registration/service.py` (`ensure_player_identity`)
- Test: extend the relevant service tests + a reconciliation test.

**Interfaces:**
- Consumes: Task 1 column + Task 3 helper. Produces: zero references to `AuthUserPlayer`
  outside the model file.

- [ ] **Step 1: Enumerate every usage** — `grep -rn "AuthUserPlayer\|player_links" backend`.
  Make a checklist; each must move to `players.user.auth_user_id`.

- [ ] **Step 2: `_linked_players_payload`** — query the single linked player and return a
  0-or-1-element list (keeps `schemas.AuthLinkedPlayer` shape; `is_primary=True`,
  `linked_at=player.created_at`):

```python
def _linked_player_payload(user) -> list[schemas.AuthLinkedPlayer]:
    p = user.player
    if p is None:
        return []
    return [schemas.AuthLinkedPlayer(player_id=p.id, player_name=p.name,
                                     is_primary=True, linked_at=p.created_at.isoformat())]
```
Eager-load `AuthUser.player` wherever `player_links` was previously loaded (replace the
`selectinload(AuthUser.player_links)` with `selectinload(AuthUser.player)`).

- [ ] **Step 3: `public_rpc.py`** — replace the `AuthUserPlayer.auth_user_id == user.id` +
  `is_primary` filter (the "resolve my player" query) with `User.auth_user_id == user.id`.

- [ ] **Step 4: `user_merge.py`** — remove the `auth.user_player` REFERENCE_CONFIG entry;
  merging now also moves `players.user.auth_user_id` if applicable (the losing player must be
  unlinked first). Add the merge rule that a player keeps at most one `auth_user_id`.

- [ ] **Step 5: `ensure_player_identity` reconciliation** (correction #9) — when the
  registration's auth_user already owns a player (`User.auth_user_id == auth_user_id`), attach
  the battletag/smurf social accounts to **that** player instead of find-or-create-by-battletag;
  if a distinct shadow player already owns the battletag, route through the merge helper.

```python
# pseudo: prefer the account-owned player, fall back to battletag dedup, else create.
owned = await session.scalar(select(User).where(User.auth_user_id == auth_user_id))
user = owned or await _find_user_by_battle_tag(session, battle_tag) or User(name=battle_tag, auth_user_id=auth_user_id)
# if owned and a different shadow already has the battletag -> merge_players(...)
```

- [ ] **Step 6: Write/extend tests** — token payload returns 0..1 players; "resolve my player"
  via `public_rpc`; reconciliation: (a) account already has player + new battletag, (b)
  colliding shadow → merge, (c) shadow-only (no account) unchanged.

- [ ] **Step 7: Run the affected suites** — `pytest` for identity/tournament/app changes.
  Expected PASS (SKIP DB-only cases when unreachable).

- [ ] **Step 8: Commit** `refactor(identity): drop AuthUserPlayer usages; reconcile player identity`.

---

### Task 6: Drop `AuthUserPlayer` class + `auth.user_player` table

**Files:**
- Modify: `backend/shared/models/auth_user.py` (delete `AuthUserPlayer`, `AuthUser.player_links`)
- Modify: `backend/shared/models/__init__.py` (drop export)
- Create: `backend/migrations/versions/iwrefac02_drop_user_player.py` (`down_revision="iwrefac01"`)
- Test: `backend/shared/tests/test_user_player_removed.py`

- [ ] **Step 1: Write the failing test** — importing `AuthUserPlayer` raises `ImportError`;
  `"user_player"` not in `Base.metadata.tables` (keyed `auth.user_player`).

- [ ] **Step 2: Run → FAIL** (still present).

- [ ] **Step 3: Delete** the class, relationship, and export. Run a full `grep -rn
  "AuthUserPlayer" backend` to confirm zero remaining references (Task 5 must be complete).

- [ ] **Step 4: Migration** — `op.drop_table("user_player", schema="auth")` in `upgrade`;
  recreate it in `downgrade` (copy the table DDL from the `a7634c02717d_initial_v5` migration
  so downgrade is real, not a stub).

- [ ] **Step 5: Apply + round-trip on anak_dev.**

- [ ] **Step 6: Run the test → PASS. Commit** `feat(identity): drop AuthUserPlayer + auth.user_player`.

---

## Part 3 — Workspace-scoped `UserPermissionDeny`

### Task 7: `UserPermissionDeny.workspace_id` + unique-constraint swap + migration

**Files:**
- Modify: `backend/shared/models/rbac.py` (`UserPermissionDeny`)
- Create: `backend/migrations/versions/iwrefac03_deny_workspace.py` (`down_revision="iwrefac02"`)
- Test: `backend/shared/tests/test_user_permission_deny_workspace.py`

**Interfaces:**
- Produces: `UserPermissionDeny.workspace_id: Mapped[int | None]` (FK `workspace.id` CASCADE,
  nullable, indexed); unique constraint over `(user_id, permission_id, COALESCE(workspace_id, 0))`.

- [ ] **Step 1: Write the failing test** — column exists, nullable, FK to `workspace.id`; the
  old `uq_user_permission_deny` unique on `(user_id, permission_id)` is gone.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Edit the model** — add `workspace_id`; replace the `UniqueConstraint("user_id",
  "permission_id", name="uq_user_permission_deny")` with a workspace-aware one. Because the
  predicate uses `COALESCE`, model it as a partial/expression unique **Index** in the model's
  `__table_args__` (SQLAlchemy can't express `COALESCE` in `UniqueConstraint`):

```python
Index("uq_user_permission_deny_user_perm_workspace",
      "user_id", "permission_id", sa.text("COALESCE(workspace_id, 0)"), unique=True),
```

- [ ] **Step 4: Migration**

```python
def upgrade() -> None:
    op.add_column("user_permission_deny",
                  sa.Column("workspace_id", sa.Integer(), nullable=True), schema="auth")
    op.create_foreign_key("fk_user_permission_deny_workspace", "user_permission_deny",
                          "workspace", ["workspace_id"], ["id"],
                          source_schema="auth", ondelete="CASCADE")
    op.drop_constraint("uq_user_permission_deny", "user_permission_deny",
                       schema="auth", type_="unique")
    op.execute(
        'CREATE UNIQUE INDEX uq_user_permission_deny_user_perm_workspace '
        'ON auth.user_permission_deny (user_id, permission_id, COALESCE(workspace_id, 0))'
    )
```
(Downgrade reverses; recreate the old unique constraint.)

> Confirm the existing constraint name with `grep -rn "uq_user_permission_deny" backend/migrations/versions`
> (created in `acctdeny0001`).

- [ ] **Step 5: Apply + round-trip on anak_dev. Step 6: Run test → PASS. Step 7: Commit**
  `feat(rbac): workspace_id on user_permission_deny`.

---

### Task 8: Deny pipeline — thread `workspace_id` end-to-end

**Files:**
- Modify: `backend/shared/models/auth_user.py` (`is_denied`, `can_capability`, `has_permission`, `has_workspace_permission`)
- Modify: `backend/identity-service/src/services/auth_token_helpers.py` (`_load_user_denies`)
- Modify: `backend/identity-service/src/schemas/auth.py` (deny entry shape in `TokenPayload`)
- Modify: `backend/identity-service/src/services/session_cache.py` (bump cache version/key)
- Test: `backend/shared/tests/test_auth_user_workspace_deny.py`

**Interfaces:**
- Consumes: Task 7 column. Produces:
  - `AuthUser.is_denied(resource, action, workspace_id: int | None = None) -> bool`
  - `AuthUser.can_capability(resource, action, workspace_id: int | None = None) -> bool`
  - `has_permission`/`has_workspace_permission` pass their workspace context into `is_denied`.
  - `_load_user_denies` emits `[{resource, action, workspace_id}]`.

- [ ] **Step 1: Write failing unit tests** over `_cached_denies` (set via `set_rbac_cache`):

```python
# A global deny (workspace_id=None) blocks everywhere; a scoped deny blocks only its workspace.
def _mk(u, denies):
    u.set_rbac_cache(role_names=[], permissions=[], workspace_rbac={}, denies=denies)

def test_global_deny_blocks_all_workspaces():
    u = AuthUser(); _mk(u, [{"resource": "registration", "action": "self_register", "workspace_id": None}])
    assert u.can_capability("registration", "self_register", workspace_id=1) is False
    assert u.can_capability("registration", "self_register", workspace_id=2) is False

def test_scoped_deny_blocks_only_its_workspace():
    u = AuthUser(); _mk(u, [{"resource": "registration", "action": "self_register", "workspace_id": 1}])
    assert u.can_capability("registration", "self_register", workspace_id=1) is False
    assert u.can_capability("registration", "self_register", workspace_id=2) is True

def test_missing_workspace_id_treated_as_global():  # backward compat (old JWT)
    u = AuthUser(); _mk(u, [{"resource": "registration", "action": "self_register"}])
    assert u.can_capability("registration", "self_register", workspace_id=1) is False
```

- [ ] **Step 2: Run → FAIL** (signature/semantics differ).

- [ ] **Step 3: Implement `is_denied`**

```python
def is_denied(self, resource: str, action: str, workspace_id: int | None = None) -> bool:
    for deny in getattr(self, "_cached_denies", None) or []:
        if deny.get("resource") != resource or deny.get("action") != action:
            continue
        ws = deny.get("workspace_id")        # missing -> global (back-compat)
        if ws is None or ws == workspace_id:
            return True
    return False

def can_capability(self, resource: str, action: str, workspace_id: int | None = None) -> bool:
    return not self.is_denied(resource, action, workspace_id)
```
In `has_permission(resource, action)` keep the existing signature but pass `workspace_id=None`
to `is_denied` (global check). In `has_workspace_permission(workspace_id, resource, action)`
change its first deny check to `self.is_denied(resource, action, workspace_id)`.

- [ ] **Step 4: `_load_user_denies`** — select `UserPermissionDeny.workspace_id` and include it:

```python
sa.select(models.Permission.resource, models.Permission.action,
          models.UserPermissionDeny.workspace_id)
  .join(models.UserPermissionDeny, models.UserPermissionDeny.permission_id == models.Permission.id)
  .where(models.UserPermissionDeny.user_id == user_id)
# -> [{"resource": r, "action": a, "workspace_id": w} for r, a, w in rows]
```
Update `schemas` so `TokenPayload.denies` entries carry the optional `workspace_id`.

- [ ] **Step 5: Bump the deny cache version** — change the Redis key/version in
  `session_cache.py` (e.g. the cache-key prefix or a stored `version` field) so pre-deploy
  entries (which lack `workspace_id`) are recomputed rather than read as stale global denies.

- [ ] **Step 6: Run all deny tests → PASS.** Also grep for every caller of `is_denied` /
  `can_capability` and confirm each passes the right `workspace_id` (or `None` deliberately):
  `grep -rn "is_denied\|can_capability" backend`.

- [ ] **Step 7: Commit** `feat(rbac): workspace-scoped deny through the token/cache pipeline`.

---

## Part 1 frontend — account / player-linking UI (single player)

### Task 9: Frontend — linking UI reflects 1:0..1; token consumers tolerate new deny field

**Files:**
- Modify: `frontend/src/services/*` + the account/linking page/components (find with
  `grep -rn "player_links\|linkPlayer\|linked.*player\|is_primary" frontend/src`).
- Test: the affected component tests (`bun test`).

- [ ] **Step 1: Locate** the linking UI and the type for linked players + deny entries.

- [ ] **Step 2:** Render at most one linked player (hide "add another" once linked; "unlink"
  remains). The API still returns a 0..1 array, so the change is presentational + types.

- [ ] **Step 3:** Confirm the token/deny TypeScript type allows the optional `workspace_id`
  on deny entries (additive — no consumer should break).

- [ ] **Step 4: Component test** — linked state shows one player + unlink; unlinked shows link.
  Run: `cd frontend && bun test <path>`.

- [ ] **Step 5: Typecheck + lint** — `cd frontend && npx tsc --noEmit && npx eslint <changed>`.

- [ ] **Step 6: Commit** `feat(account): single-player linking UI`.

**Phase A deliverable:** `players.user` owns the account link (provisioned at signup),
`AuthUserPlayer` is gone, and per-user denies can be scoped to a workspace — all
backward-compatible at the API boundary.

---

## Self-Review

- **Spec coverage:** Part 1 — column+rel (T1), migration+primary backfill (T2), signup
  provisioning (T3), link service (T4), usage sweep + reconciliation (T5), drop table (T6);
  Part 3 — model+migration (T7), full deny pipeline (T8); frontend (T9). Corrections #1–#5,
  #7, #9, #10 all land in Phase A.
- **Placeholder scan:** discovery points (OAuth AuthUser site, deny-constraint name, FK column
  type) each name the exact file/grep to read — concrete reuse, not "TBD".
- **Type consistency:** `auth_user_id` (players.user), `is_denied(resource, action, workspace_id)`,
  `can_capability(..., workspace_id)`, deny dict `{resource, action, workspace_id}` used
  identically across T1/T4/T5/T7/T8 and carried into Phases B/C.
