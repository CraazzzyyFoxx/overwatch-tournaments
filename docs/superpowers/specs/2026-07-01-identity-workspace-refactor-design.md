# Identity / Workspace Schema Refactor — Design

- **Date:** 2026-07-01
- **Status:** Approved (design) — pending implementation
- **Source:** `docs/tz_identity_workspace_refactor.md` (TZ) + `docs/workspace_member_erd_1.mermaid` (target ERD)
- **Scope:** Backend schema + RBAC + identity flows across `shared`, `identity-service`,
  `app-service`, `tournament-service`, `balancer-service`, `parser-service`, plus the
  frontend reads that depend on the changed token/API shapes. Delivered in **3 phases**
  (A → B → C). The Go gateway only changes if a route's request/response contract changes
  (none planned; bodies are pass-through).

## Context & goal

Identity and membership are modeled inconsistently today:

- The link between a login (`auth.user`) and a game identity (`players.user`) lives in an
  M2M table `auth.user_player` (`AuthUserPlayer`) with an `is_primary` flag, even though the
  real invariant enforced in code (`identity-service/.../player_link_service.py`) is **one
  `players.user` → at most one `auth.user`**. The "many players per account" capability is an
  unused historical artifact.
- `workspace_member` is keyed on `auth_user_id` and carries a **denormalized `role: str`**
  that drifts from the RBAC system.
- Domain rows (`balancer.registration`, `tournament.player`, achievements) variously key on
  `auth_user_id` or directly on `players.user.id`, so "data belongs to a member of this
  workspace" is not expressible as a single foreign key.

**Goal** — one transparent model:

- **`players.user`** = global identity backbone (one real human, including shadow players
  imported from match logs / CSV). Gains a unique, nullable `auth_user_id` (NULL = shadow).
- **`workspace_member`** = the operational anchor for all workspace-isolated domain logic
  (RBAC, registrations, analytics, achievements), keyed on `player_id`. No denormalized role.
- **Data is workspace-isolated by default**; a cross-workspace query is an explicit join
  through `workspace_member.player_id → players.user`.

The target ERD is `docs/workspace_member_erd_1.mermaid`.

## Verified current state (the spec is written against the real code, not the TZ prose)

| Area | Reality (file) |
|---|---|
| `players.User` | `shared/models/user.py`: `id` (BigInteger), `name` (unique), `avatar_url`, `social_accounts`. **No `auth_user_id`.** |
| `AuthUser` | `shared/models/auth_user.py`: `player_links: list[AuthUserPlayer]`; perm methods `is_denied(resource, action)`, `can_capability(resource, action)`, `has_permission`, `has_workspace_permission(workspace_id, …)` read `_cached_denies` (list of `{resource, action}` dicts) set via `set_rbac_cache`. |
| `AuthUserPlayer` | `auth.user_player`: `auth_user_id`, `player_id` **(unique)**, `is_primary`. One auth_user MAY link several players. |
| `UserPermissionDeny` | `shared/models/rbac.py` (`auth.user_permission_deny`): column **`user_id`** (not `auth_user_id`), `permission_id`, `reason`, `created_by`; `UniqueConstraint("user_id","permission_id")`; **no `workspace_id`**. From migration `acctdeny0001`. |
| Deny pipeline | `identity-service/.../auth_token_helpers.py`: `_load_user_denies` → `[{resource, action}]`, cached in Redis (`session_cache.set_rbac`) AND embedded in the JWT (`schemas.TokenPayload.denies`); consumed via `set_rbac_cache` → `_cached_denies` → `is_denied`. |
| `WorkspaceMember` | `shared/models/workspace.py`: `workspace_id`, `auth_user_id` (FK auth.user), `role: str`="member"; `UniqueConstraint(workspace_id, auth_user_id)`. Created only in `app-service/.../workspace/service.py::add_member`. Token built in `auth_token_helpers._build_access_token_payload` joins on `auth_user_id`, emits `role`. |
| `BalancerRegistration` | `balancer.registration`: `tournament_id`, `workspace_id`, `auth_user_id` (nullable), `user_id`→players (nullable). Unique idx `uq_balancer_registration_user (tournament_id, auth_user_id) WHERE deleted_at IS NULL`. Filtered by `auth_user_id` in `shared/repository/registration.py::get_active_for_user` + `tournament-service/.../registration/service.py::get_registration`. |
| `Player` | `tournament.player`: `user_id`→players **(NOT NULL)**, `tournament_id`, `team_id`; idx `ix_player_user_tournament`, `ix_player_team_user`, `ix_player_user_not_sub`. |
| Achievements | `shared/models/achievement.py`: active = `AchievementEvaluationResult` + `AchievementOverride` (`user_id`→players + nullable `workspace_id`/`tournament_id`/`match_id`). `AchievementUser` + `Achievement` are **legacy** (not workspace-aware). Reads: `shared/services/achievement_effective.py`, `app-service/.../achievements/service_v2.py`, `parser-service/.../achievement/engine/differ.py`; merge audit `app-service/.../admin/user_merge.py`. |
| Lazy player | `tournament-service/.../registration/service.py::ensure_player_identity` creates `players.User(name=battle_tag)`, dedup by normalized handle; called from `create_registration` (already has `workspace_id` + `auth_user_id`). |
| Alembic | head **`oauthmulti0001`**; `BigInteger` ids, explicit `schema=`, `include_schemas=True`, version table in `public`. Id convention = short semantic codes (`acctdeny0001`). |
| Helper | **No `get_or_create_workspace_member`** exists (only reads in `shared/repository/workspace.py`). |

## Corrections to the TZ (carried into every plan)

The TZ is directionally correct but wrong or silent on these — each is load-bearing:

1. **`UserPermissionDeny` column is `user_id`**, not `auth_user_id` (TZ §3 / ERD mislabel).
2. **Workspace-scoped deny is a pipeline change, not one method (TZ §3).** It spans:
   model (`workspace_id` + unique-constraint swap) → `_load_user_denies` (select + emit
   `workspace_id`) → `TokenPayload`/deny schema → `session_cache` payload (bump the cache
   key/version so stale global denies don't linger) → `AuthUser.is_denied(resource, action,
   workspace_id=None)` and threading `workspace_id` through `can_capability`,
   `has_permission`, `has_workspace_permission` and every caller. **Backward-compat:** a deny
   dict missing `workspace_id` (old JWT) is treated as a global deny.
3. **`can_capability` gains `workspace_id`** (TZ §2.5 calls
   `can_capability(tournament.workspace_id, "registration", "self_register")`).
4. **`WORKSPACE_SYSTEM_ROLE_NAMES` is a tuple** plus a `permission_names_for_workspace_role()`
   switch — adding `player` needs both: append `"player"` and add a branch returning `()`
   (empty perms; self-register is an allow-by-default capability, not a granted permission).
5. **Part-1 data-migration hazard.** Because one auth_user may link several players, the TZ's
   blanket `UPDATE players.user SET auth_user_id = up.auth_user_id` would assign one auth_user
   to multiple players and violate `UNIQUE(auth_user_id)`. **Resolution:** backfill from the
   `is_primary` link only; non-primary linked players keep `auth_user_id = NULL` (become shadow
   players). A pre-migration audit query (`auth_users with >1 link`) is part of the plan and is
   a flagged go/no-go decision point with the user.
6. **Recreate the registration unique index** as `(tournament_id, workspace_member_id) WHERE
   deleted_at IS NULL` when `auth_user_id` is dropped (TZ §4 omits `uq_balancer_registration_user`).
7. **`AuthUserPlayer` call sites the TZ misses:** `tournament-service/.../public_rpc.py:369,397`
   (`AuthUserPlayer.auth_user_id` + `is_primary`) and the token path
   `auth_token_helpers._linked_players_payload` + `schemas.AuthLinkedPlayer` +
   `AuthUser.player_links`.
8. **Achievements:** migrate the **active** models only (`AchievementEvaluationResult`,
   `AchievementOverride`); legacy `AchievementUser`/`Achievement` are explicitly left as-is
   (or dropped in a later cleanup). **Player-centric reads** (public profile, analytics group
   by player) must re-derive `player_id` via `JOIN workspace_member ON workspace_member.id =
   <table>.workspace_member_id`. `user_merge.py` REFERENCE_CONFIG entries change from
   `<schema>.<table>.user_id` to routing through `workspace_member`.
9. **Signup provisioning vs. battletag dedup (trickiest risk).** Part 1 makes signup create
   `players.User(name=username_or_email, auth_user_id=…)`. Then at registration,
   `ensure_player_identity` must reconcile: if the auth_user already owns a player, attach the
   battletag/smurf social accounts to **that** player; if an independent shadow player already
   exists for the battletag, that is a **merge** (reuse/extend `user_merge.py`). Getting this
   wrong silently splits or merges identities.
10. **Frontend in scope.** Multi→single player linking UI, any read of the token's denormalized
    `workspace.role`, and registration/achievement views that assume the old shape. Phases A/B
    keep the **token/API contract backward-compatible** (derive `role` from RBAC; emit linked
    players as a 0..1 array) so the only forced FE work is the linking UI; remaining FE reads
    are addressed in Phase C.

## Design — the 6 parts

### Part 1 — Collapse `auth.user_player` into `players.user.auth_user_id`
- Add `players.User.auth_user_id: int | None` (FK `auth.user.id` `ON DELETE SET NULL`,
  unique, indexed). NULL = shadow player.
- `AuthUser.player_links` → `AuthUser.player` (1:0..1, `uselist=False`). The token's linked-
  players payload becomes a 0-or-1-element array for FE compatibility.
- Provision `players.User(auth_user_id=…)` at **signup** (password + OAuth), in the same
  transaction as `AuthUser` creation.
- `PlayerLinkService.link/unlink` become `UPDATE players.user SET auth_user_id = … / NULL`.
- Drop `AuthUserPlayer` + `auth.user_player`.

### Part 2 — `workspace_member` as the anchor
- `WorkspaceMember`: add `player_id` (FK `players.user.id` CASCADE); drop `auth_user_id` and
  `role`. Constraints: `UniqueConstraint(workspace_id, player_id)` and
  `UniqueConstraint(id, workspace_id)` (lets later tables hang a composite FK that pins a row
  to its workspace).
- System role **`player`** (empty permission set) added to the catalog.
- New capability **`registration.self_register`** (allow-by-default). A per-player ban in a
  workspace = `user_permission_deny(user_id, permission_id=<self_register>, workspace_id=<ws>)`.
- On first tournament registration: `get_or_create_workspace_member(workspace_id, player_id)`,
  grant the `player` role, and gate on `can_capability(workspace_id, "registration",
  "self_register")` (403 if denied).
- The denormalized `WorkspaceMembership.role` in the token is **derived from RBAC**
  (`legacy_workspace_role_name_for_user`, which already exists) to preserve the contract.

### Part 3 — `UserPermissionDeny` workspace-scoped
- Add nullable `workspace_id` (FK `workspace.id` CASCADE). Swap unique constraint to
  `(user_id, permission_id, COALESCE(workspace_id, 0))`.
- Deny semantics: `workspace_id IS NULL` denies globally; a concrete `workspace_id` denies
  only there. Implemented end-to-end through the deny pipeline (correction #2).

### Part 4 — `balancer.registration` on `workspace_member_id`
- Add `workspace_member_id` (FK `workspace.workspace_member.id` `ON DELETE SET NULL`,
  nullable — NULL = sheet/CSV import without an account). Drop `auth_user_id` and the
  denormalized `workspace_id`. Keep `user_id`→players (independent battletag dedup).
- Recreate `uq_balancer_registration_user` on `(tournament_id, workspace_member_id)`.
- Workspace is derived via `tournament_id → Tournament.workspace_id`.

### Part 5 — `tournament.player` on `workspace_member_id`
- Replace `user_id` with `workspace_member_id` (FK `workspace.workspace_member.id` CASCADE,
  NOT NULL). Swap indexes to `ix_player_workspace_member_tournament` and
  `ix_player_team_workspace_member` (and the partial `is_substitution=false` variant).

### Part 6 — Achievements on `workspace_member_id`
- `AchievementEvaluationResult.user_id` and `AchievementOverride.user_id` →
  `workspace_member_id` (FK CASCADE, NOT NULL). Backfill via `(workspace_id, player_id)`.
- Reads re-derive `player_id` through `workspace_member` for player-centric grouping.

## Sequencing & dependencies

1. **Phase A** = Part 1 + Part 3 — additive and backward-compatible; shippable alone.
2. **Phase B** = Part 2 — depends on A (needs `players.user.auth_user_id` to backfill
   `workspace_member.player_id`).
3. **Phase C** = Parts 4, 5, 6 + dependent frontend — depend on B; parallelizable among themselves.

## Invariants (run on anak_dev after each phase)

```sql
-- Bijection: no auth_user maps to >1 player
SELECT auth_user_id, COUNT(*) FROM players."user"
WHERE auth_user_id IS NOT NULL GROUP BY auth_user_id HAVING COUNT(*) > 1;          -- 0 rows

-- Every member has an identity
SELECT COUNT(*) FROM workspace.workspace_member WHERE player_id IS NULL;           -- 0

-- No orphan registration member FK
SELECT COUNT(*) FROM balancer.registration r
LEFT JOIN workspace.workspace_member wm ON wm.id = r.workspace_member_id
WHERE r.workspace_member_id IS NOT NULL AND wm.id IS NULL;                         -- 0

-- Every roster player resolves to a member
SELECT COUNT(*) FROM tournament.player WHERE workspace_member_id IS NULL;          -- 0
```

Pre-Phase-A audit (decision gate for correction #5):

```sql
SELECT auth_user_id, COUNT(*) FROM auth.user_player GROUP BY auth_user_id HAVING COUNT(*) > 1;
```

## Risks

- **R1 (high) — multi-player accounts** (correction #5): if any auth_user has >1 link, the
  non-primary players silently become shadows. Surfaced by the audit query; confirm the list
  with the user before Phase A backfill.
- **R2 (high) — identity reconciliation** (correction #9): signup-provisioned player vs.
  battletag shadow player. Covered by explicit `ensure_player_identity` reconciliation tests
  (already-linked, new battletag, colliding shadow → merge).
- **R3 (med) — deny cache staleness** (correction #2): bump the `session_cache` schema/key so
  pre-deploy JWTs/Redis entries don't apply a global deny where a workspace one is meant.
- **R4 (med) — derived `role` contract**: the token must keep emitting a per-workspace `role`
  string after Part 2 drops the column; derive it from RBAC.
- **R5 (low) — FK column type**: existing achievement migrations used `sa.Integer()` for
  `user_id` though `players.user.id` is `BigInteger`. New `workspace_member_id` columns use
  `sa.BigInteger()` to match `workspace_member.id`; verify FK type compatibility at apply time.

## What does NOT change

- `overwatch_rank` / `rank_snapshot` stay on `players.user.id` (facts about a battletag).
- `social_account` / `social_account_visibility` — already correct.
- `user_roles` stays on `auth_user_id` (JWT is issued per `auth.user`).
- `has_workspace_permission` grant logic — unchanged except the deny threading (Part 3).

## Out of scope

- Dropping legacy `AchievementUser` / `Achievement` (separate cleanup).
- Gateway route contract changes (none needed).
- Any rework of OW-rank / rank-snapshot ownership.
```
