# Identity/Workspace Refactor — Phase B (Workspace-Member Anchor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-base `workspace_member` on `players.user.id` (`player_id`), drop the
denormalized `role` string, add a `player` system role + a `registration.self_register`
capability, and auto-enroll players as workspace members on their first tournament registration.

**Architecture:** `workspace_member` becomes the identity anchor (`workspace_id, player_id`
unique). The token keeps emitting a per-workspace `role` string, now **derived from RBAC**
instead of stored. First registration creates the member, grants the `player` role, and is
gated by the new allow-by-default capability (which a per-workspace deny can revoke).

**Tech Stack:** Python 3 (SQLAlchemy async, Alembic, FastStream RPC). Depends on **Phase A**
(`players.user.auth_user_id` must exist to backfill `workspace_member.player_id`).
Design spec: `docs/superpowers/specs/2026-07-01-identity-workspace-refactor-design.md`.

## Global Constraints

- ORM in `backend/shared/models/`; migrations in `backend/migrations/versions/`, chained from
  Phase A's last migration (`iwrefac03`); set `down_revision` from `alembic heads` at execution.
- `db.TimeStampIntegerMixin` → `id` BigInteger. New FK to `players.user.id` follows existing
  FK column typing in migrations.
- `WORKSPACE_SYSTEM_ROLE_NAMES` is a **tuple** in `shared/rbac/catalog.py`; role→permission
  mapping is the `permission_names_for_workspace_role()` switch. Editing one requires the other.
- The token's `WorkspaceMembership.role` field MUST keep being populated (compat) — derive it
  with the existing `legacy_workspace_role_name_for_user`.
- Migrations: anak_dev only; round-trip each. TDD; commit per task; no push unless asked.
- Prefix git/test/build with `rtk`; edit files via Edit/Write only.

---

### Task 1: `WorkspaceMember` keyed on `player_id`; drop `auth_user_id` + `role`

**Files:**
- Modify: `backend/shared/models/workspace.py` (`WorkspaceMember`)
- Test: `backend/shared/tests/test_workspace_member_player_anchor.py`

**Interfaces:**
- Produces: `WorkspaceMember.player_id: Mapped[int]` (FK `players.user.id` CASCADE),
  `WorkspaceMember.player` rel; `UniqueConstraint(workspace_id, player_id)` +
  `UniqueConstraint(id, workspace_id)`. Removes `auth_user_id`, `auth_user`, `role`.

- [ ] **Step 1: Write the failing test**

```python
# backend/shared/tests/test_workspace_member_player_anchor.py
from shared.models.workspace import WorkspaceMember

def test_member_anchored_on_player():
    cols = set(WorkspaceMember.__table__.columns.keys())
    assert "player_id" in cols
    assert "auth_user_id" not in cols
    assert "role" not in cols
    uniques = [c for c in WorkspaceMember.__table__.constraints
               if c.__class__.__name__ == "UniqueConstraint"]
    sets = [{col.name for col in u.columns} for u in uniques]
    assert {"workspace_id", "player_id"} in sets
    assert {"id", "workspace_id"} in sets
```

- [ ] **Step 2: Run → FAIL.**

Run: `cd backend && uv run --package shared pytest shared/tests/test_workspace_member_player_anchor.py -v`

- [ ] **Step 3: Edit the model**

```python
class WorkspaceMember(db.TimeStampIntegerMixin):
    __tablename__ = "workspace_member"
    __table_args__ = (
        UniqueConstraint("workspace_id", "player_id", name="uq_workspace_member_workspace_player"),
        UniqueConstraint("id", "workspace_id", name="uq_workspace_member_id_workspace"),
    )
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"), index=True)
    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    player: Mapped["User"] = relationship()
```
Remove `auth_user_id`, the `auth_user` relationship, and `role`. Add the `User` TYPE_CHECKING import.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit** `feat(workspace): WorkspaceMember anchored on player_id`.

---

### Task 2: Migration — backfill `player_id`, drop `auth_user_id`/`role`

**Files:**
- Create: `backend/migrations/versions/iwrefac04_member_player.py` (`down_revision="iwrefac03"`)

**Interfaces:**
- Produces: `workspace_member.player_id` NOT NULL + FK + the two unique indexes;
  `auth_user_id` and `role` dropped.

- [ ] **Step 1: Write the migration**

```python
def upgrade() -> None:
    op.add_column("workspace_member", sa.Column("player_id", sa.Integer(), nullable=True),
                  schema="workspace")
    op.execute(
        """
        UPDATE workspace.workspace_member wm
        SET player_id = pu.id
        FROM players."user" pu
        WHERE pu.auth_user_id = wm.auth_user_id
        """
    )
    # Safety: any member whose auth_user has no player yet (should be none after Phase A
    # signup provisioning) — create a shadow player so the column can go NOT NULL.
    op.execute(
        """
        INSERT INTO players."user" (name, auth_user_id, created_at)
        SELECT au.username, au.id, now()
        FROM workspace.workspace_member wm
        JOIN auth."user" au ON au.id = wm.auth_user_id
        WHERE wm.player_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM players."user" p WHERE p.auth_user_id = au.id)
        """
    )
    op.execute(
        """
        UPDATE workspace.workspace_member wm
        SET player_id = pu.id
        FROM players."user" pu
        WHERE pu.auth_user_id = wm.auth_user_id AND wm.player_id IS NULL
        """
    )
    op.alter_column("workspace_member", "player_id", nullable=False, schema="workspace")
    op.create_foreign_key("fk_workspace_member_player", "workspace_member", "user",
                          ["player_id"], ["id"], source_schema="workspace",
                          referent_schema="players", ondelete="CASCADE")
    op.create_unique_constraint("uq_workspace_member_workspace_player", "workspace_member",
                                ["workspace_id", "player_id"], schema="workspace")
    op.create_unique_constraint("uq_workspace_member_id_workspace", "workspace_member",
                                ["id", "workspace_id"], schema="workspace")
    op.drop_constraint("workspace_member_workspace_id_auth_user_id_key", "workspace_member",
                       schema="workspace", type_="unique")  # confirm real name
    op.drop_column("workspace_member", "auth_user_id", schema="workspace")
    op.drop_column("workspace_member", "role", schema="workspace")
```
Downgrade reverses (re-add `auth_user_id`/`role`, backfill `auth_user_id` from
`players.user.auth_user_id`, restore the old unique constraint).

> Confirm the existing `UniqueConstraint(workspace_id, auth_user_id)` autogenerated name via
> `\d workspace.workspace_member` on anak_dev or `grep -rn "workspace_member" backend/migrations/versions`.

- [ ] **Step 2: Apply + round-trip on anak_dev.**

- [ ] **Step 3: Verify invariant** — `SELECT COUNT(*) FROM workspace.workspace_member WHERE player_id IS NULL;` → 0.

- [ ] **Step 4: Commit** `feat(workspace): migrate workspace_member to player_id; drop auth_user_id/role`.

---

### Task 3: `get_or_create_workspace_member` helper + creation sites on `player_id`

**Files:**
- Modify: `backend/shared/repository/workspace.py` (add creation + get-or-create over `player_id`)
- Modify: `backend/app-service/src/services/workspace/service.py` (`add_member`, `add_member_with_roles`, `get_member`, `update_member_role`)
- Test: `backend/app-service/tests/test_workspace_member_helpers.py`

**Interfaces:**
- Produces: `async def get_or_create_workspace_member(session, *, workspace_id: int,
  player_id: int) -> WorkspaceMember` (idempotent via `uq_workspace_member_workspace_player`).
- `add_member(session, workspace_id, player_id, ...)` no longer takes/writes `role`.
- `update_member_role` is removed/repointed to RBAC role assignment (no stored `role`).

- [ ] **Step 1: Write failing tests** — `get_or_create_workspace_member` returns the same row
  on a second call; `add_member` creates a member by `player_id` and the system roles exist.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** the repository helper (insert-or-select on the unique constraint),
  repoint `add_member`/`add_member_with_roles` to `player_id`, and replace `member.role`
  reads/writes with RBAC role assignment (`assign_workspace_system_role` /
  `replace_user_workspace_roles`, which key on `auth_user_id` for `user_roles` — unchanged).

> `user_roles` (RBAC) stays on `auth_user_id` per the spec; only `workspace_member` moves to
> `player_id`. `add_member_with_roles` therefore needs both the `player_id` (for the member row)
> and the `auth_user_id` (for RBAC role assignment) — pass both.

- [ ] **Step 4: Run → PASS** (SKIP DB cases when unreachable).

- [ ] **Step 5: Commit** `feat(workspace): get_or_create_workspace_member + player_id creation`.

---

### Task 4: Token payload — membership via `player_id`; derive `role` from RBAC

**Files:**
- Modify: `backend/identity-service/src/services/auth_token_helpers.py` (`_build_access_token_payload`)
- Test: `backend/identity-service/tests/test_token_workspace_membership.py`

**Interfaces:**
- Consumes: Phase A `players.user.auth_user_id`, Task 1/3. Produces: the workspace-membership
  query joins `workspace_member.player_id → players.user.auth_user_id == current_user.id`; the
  emitted `WorkspaceMembership.role` is derived from RBAC (compat).

- [ ] **Step 1: Write failing test** — a user who is a member of workspace W gets a
  `WorkspaceMembership` for W with a non-empty `role` derived from their RBAC role (e.g.
  `owner`/`admin`/`member`/`player`), even though `workspace_member.role` no longer exists.

- [ ] **Step 2: Run → FAIL** (query still references `workspace_member.auth_user_id`/`role`).

- [ ] **Step 3: Rewrite the membership query**

```python
workspace_rows = await session.execute(
    sa.select(models.WorkspaceMember.workspace_id, models.Workspace.slug)
    .join(models.Workspace, models.Workspace.id == models.WorkspaceMember.workspace_id)
    .join(models.User, models.User.id == models.WorkspaceMember.player_id)
    .where(models.User.auth_user_id == current_user.id)
)
```
Drop the `WorkspaceMember.role` selection; compute each membership's `role` from the cached
workspace RBAC (`legacy_workspace_role_name_for_user`, or map the user's highest workspace role
name). Keep the `WorkspaceMembership.role` field populated.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit** `feat(auth): token workspace membership via player_id + derived role`.

---

### Task 5: RBAC catalog — `player` system role + `registration.self_register` capability

**Files:**
- Modify: `backend/shared/rbac/catalog.py`
- Test: `backend/shared/tests/test_rbac_catalog_player_role.py`

**Interfaces:**
- Produces: `"player"` in `WORKSPACE_SYSTEM_ROLE_NAMES`; `permission_names_for_workspace_role("player") == ()`;
  `("registration", "self_register")` in `PERMISSION_CATALOG`.

- [ ] **Step 1: Write the failing test**

```python
from shared.rbac.catalog import (
    WORKSPACE_SYSTEM_ROLE_NAMES, PERMISSION_CATALOG, permission_names_for_workspace_role,
)

def test_player_role_and_self_register():
    assert "player" in WORKSPACE_SYSTEM_ROLE_NAMES
    assert permission_names_for_workspace_role("player") == ()
    assert ("registration", "self_register") in {(p.resource, p.action) for p in PERMISSION_CATALOG}
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Edit the catalog** — append `"player"` to the tuple; add the
  `if role_name == "player": return ()` branch to `permission_names_for_workspace_role`; add
  `_permission("registration", "self_register", "Self-register for a tournament")` to
  `PERMISSION_CATALOG`.

> `self_register` is an allow-by-default **capability** checked via `can_capability`; it is NOT
> in any role's granted set (a deny revokes it). The empty `player` role exists so first-time
> registrants are real workspace members without inheriting `member`'s read permissions unless
> the workspace chooses to.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit** `feat(rbac): player system role + registration.self_register capability`.

---

### Task 6: Auto-enroll + capability gate at first registration

**Files:**
- Modify: `backend/tournament-service/src/services/registration/service.py` (`create_registration`)
- Test: `backend/tournament-service/tests/test_registration_self_register_gate.py`

**Interfaces:**
- Consumes: Phase A `auth_user.player`, Task 3 helper, Task 5 capability + role; the auth
  context in `create_registration` (it already receives `auth_user_id` + `workspace_id`).
- Produces: on registration, the player's `workspace_member` is ensured and granted the
  `player` role; a denied `self_register` capability raises 403.

- [ ] **Step 1: Write failing tests** — (a) first registration creates a `workspace_member`
  for the player + a `player` RBAC role assignment; (b) a user with a workspace-scoped
  `self_register` deny gets 403; (c) a second registration does not duplicate the member.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** — before creating the `BalancerRegistration` (after the player
  identity is resolved), resolve the auth_user, check the capability, ensure the member, grant
  the role:

```python
auth_user = await _load_auth_user_with_rbac(session, auth_user_id)  # reuse existing loader
if not auth_user.can_capability(workspace_id, "registration", "self_register"):
    raise HTTPException(status_code=403, detail="Registration is not allowed for this user in this workspace")
member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)
await ensure_workspace_system_roles(session, workspace_id)
await assign_workspace_system_role(session, user_id=auth_user_id, workspace_id=workspace_id, role_name="player")  # idempotent
```
`player_id` comes from `ensure_player_identity` (which after Phase A prefers the account-owned
player). For sheet/CSV imports there is no auth_user → skip the gate and member creation
(those registrations have no `workspace_member`, consistent with Phase C's nullable FK).

> Confirm the existing RBAC-loaded AuthUser accessor used elsewhere in tournament-service
> (`grep -rn "get_user_with_rbac\|set_rbac_cache\|can_capability" backend/tournament-service`)
> so the cached denies are present when `can_capability` is called.

- [ ] **Step 4: Run → PASS** (SKIP DB cases when unreachable).

- [ ] **Step 5: Commit** `feat(registration): auto-enroll workspace member + self_register gate`.

**Phase B deliverable:** `workspace_member` is the identity anchor, the denormalized `role`
is gone (derived from RBAC for the token), and registration enrolls members + enforces the
deniable `self_register` capability.

---

## Self-Review

- **Spec coverage (Part 2):** model (T1), migration+backfill (T2), creation helper + sites
  (T3), token membership + derived role (T4), `player` role + `self_register` (T5), auto-enroll
  + gate (T6). Corrections #3 (`can_capability(workspace_id,…)`), #4 (tuple+switch), and the
  derived-`role` contract (R4) are all covered.
- **Placeholder scan:** discovery points (old unique-constraint name, RBAC AuthUser loader)
  name the exact grep/inspection — concrete, not "TBD".
- **Type consistency:** `player_id`, `get_or_create_workspace_member(workspace_id, player_id)`,
  `can_capability(workspace_id, resource, action)` match Phase A's signatures and feed Phase C
  (which keys domain rows on `workspace_member.id`).
- **Cross-phase dependency:** requires Phase A complete (`players.user.auth_user_id` populated)
  before T2's backfill.
