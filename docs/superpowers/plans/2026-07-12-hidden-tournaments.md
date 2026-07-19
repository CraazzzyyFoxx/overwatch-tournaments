# Hidden (preview) Tournaments — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a tournament be marked hidden so it — and every nested read across tournament-service and app-service — is visible only to workspace admins and a per-tournament preview allowlist; everyone else never sees it in listings and gets 404 on any direct read.

**Architecture:** One shared boolean `Tournament.is_hidden` + a new `TournamentPreviewAccess(tournament_id, auth_user_id)` allowlist table. All authorization funnels through a single shared module `shared/services/tournament_visibility.py` (`can_view_tournament`, `assert_tournament_viewable`, `visible_tournaments_predicate`). Every tournament-scoped read RPC in both Python services rehydrates OPTIONAL identity and calls the shared guard; list queries filter at the SQL level. The Go gateway flips affected read routes `AuthNone → AuthOptional`, adds admin allowlist CRUD routes, and gates WS `tournament:*` topics.

**Tech Stack:** Python 3.12 (SQLAlchemy 2 async, FastStream/RabbitMQ RPC, cashews, Alembic, pydantic v2, pytest), Go (gateway, pgx), Next.js 15 (App Router, TanStack Query, next-intl, shadcn), UV workspace.

## Global Constraints

- `Tournament.is_hidden`: `Boolean()`, `default=False`, `server_default="false"`, `nullable=False`, indexed. Orthogonal to `TournamentStatus`. Existing rows stay visible.
- Allowlist keyed on `auth_user` (viewer must be logged in). FK → `auth.user.id`, `ondelete=CASCADE`.
- **404, not 403**, for hidden tournaments the viewer cannot see (no existence disclosure).
- Filter lists at the **query level**, never post-serialization.
- Alembic migration adds at current head `mvpimp0001` (`down_revision = "mvpimp0001"`).
- Cache gotcha: public read caches (cashews) are keyed WITHOUT the viewer. The visibility gate MUST run BEFORE the cached read (`tournament_flows.get_read` is `@cache`d). Never gate inside a cached function.
- WS ACL ≠ REST auth: `tournament:{id}:*` topics need their own visibility check.
- i18n: next-intl. `t(key)` for a message containing `{x}` with no values THROWS — always pass values. `next build` masks TS errors → verify with `bunx tsc --noEmit`.
- Windows: edit files only with Edit/Write tools (preserve UTF-8), never Set-Content.
- Superuser bypasses every check (`AuthUser.is_workspace_admin` already returns True for superusers).
- Commit conventional messages; do NOT push or touch master/develop without approval.

## Canonical visibility rule (implement exactly)

```
can_view_tournament(user, tournament, preview_user_ids):
    if not tournament.is_hidden: return True
    if user is None: return False
    if user.is_workspace_admin(tournament.workspace_id): return True   # superuser included
    return user.id in preview_user_ids
```

SQL list predicate (`visible_tournaments_predicate(user)`), applied to both the page query and the count query:
- anonymous: `Tournament.is_hidden == False`
- superuser: no filter (return `sa.true()`)
- logged-in non-super: `OR(is_hidden == False, workspace_id IN <admin ws ids>, id IN <select preview_access.tournament_id where auth_user_id == user.id>)` where `<admin ws ids>` = the workspaces from the JWT cache where `user.is_workspace_admin(ws)` is true.

---

## File Structure

**Shared (`backend/shared`)**
- Modify `models/tournament/tournament.py` — add `is_hidden` column.
- Create `models/tournament/preview_access.py` — `TournamentPreviewAccess`.
- Modify `models/tournament/__init__.py` — export it.
- Create `services/tournament_visibility.py` — the guard (async loaders, `can_view_tournament`, `assert_tournament_viewable`, `visible_tournaments_predicate`, `admin_visible_workspace_ids`).
- Modify `rpc/identity.py` — add non-raising `rehydrate_user_optional`.
- Create `migrations/versions/hidden0001_add_tournament_hidden_preview.py`.
- Tests: `shared/tests/test_tournament_visibility.py` (pure unit), `shared/tests/test_preview_access_model.py`.

**tournament-service (`backend/tournament-service/src`)**
- Modify `rpc/reads.py` — gate get_tournament/get_stages/get_standings/get_match/get_encounter/get_team/get_match_kill_feed/list_tournaments/list_encounters/list_matches/list_teams.
- Modify `rpc/public_rpc.py` — gate reg_pub_form/reg_pub_list/reg_pub_get_me and other tournament-scoped public reads.
- Modify `services/tournament/service.py` — `get_all` accepts a visibility predicate.
- Modify `services/tournament/flows.py` — `get_all` threads viewer; `to_pydantic` sets `is_hidden`.
- Modify `schemas/tournament.py` — `TournamentRead.is_hidden`.
- Modify `schemas/admin/tournament.py` — `TournamentUpdate.is_hidden` (+ `TournamentCreate.is_hidden` optional).
- Create `services/visibility_resolvers.py` — resolve tournament_id for encounter/team/match/encounter_map ids.
- Modify `rpc/admin_misc.py` — 3 preview-access admin RPCs.
- Tests: `tests/test_tournament_visibility_reads.py`, `tests/test_preview_access_admin.py`.

**gateway (`gateway/internal`)**
- Modify `tournament/routes.go` — flip 8 read routes to `AuthOptional`; add 3 preview-access admin routes (new table `PreviewAccessRoutes` or extend `AdminMiscRoutes`).
- Modify `app/routes.go` + `app/achievements_routes.go` — flip tournament-scoped app reads to `AuthOptional`.
- Modify `workspace/workspace.go` — add `TournamentIsHidden`, `IsPreviewAllowed`, `EncounterTournamentID` lookups.
- Modify `acl/acl.go` — gate `tournament:*:bracket|draft`, `encounter:*:map-veto` for hidden tournaments.
- Modify `acl/acl_test.go` — cover the new gate.

**frontend (`frontend/src`)**
- Modify `types/tournament.types.ts` (Tournament.is_hidden), `types/admin.types.ts` (TournamentUpdateInput.is_hidden + PreviewAccessEntry type).
- Modify `services/admin.service.ts` — preview-access list/add/remove + is_hidden in update.
- Modify `app/admin/tournaments/[id]/components/tournamentWorkspace.helpers.ts` + `TournamentSettingsTab.tsx` — Visibility card + allowlist editor.
- Modify `app/(site)/tournaments/components/TournamentsTable.tsx` — Hidden/Preview badge.
- Modify `app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx` — preview banner.
- Modify `i18n/messages/en.json` + `ru.json` — keys (keep parity for `messages.parity.test.ts`).

---

## Phase 1 — Shared data model + migration

### Task 1: `is_hidden` column on Tournament

**Files:** Modify `backend/shared/models/tournament/tournament.py`

- [ ] Add after the `is_finished` column (line 40):

```python
    is_hidden: Mapped[bool] = mapped_column(
        Boolean(), default=False, server_default="false", nullable=False, index=True
    )
```

- [ ] Commit: `feat(shared): add Tournament.is_hidden column`

### Task 2: `TournamentPreviewAccess` model

**Files:** Create `backend/shared/models/tournament/preview_access.py`; Modify `backend/shared/models/tournament/__init__.py`

- [ ] Create the model (mirrors WorkspaceMember cross-schema FK style; `auth.user` per auth_user.py:39-40):

```python
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("TournamentPreviewAccess",)


class TournamentPreviewAccess(db.TimeStampIntegerMixin):
    """Per-tournament preview allowlist: logged-in auth users who may view a
    hidden tournament (and all its nested data) even without workspace-admin
    rights. Keyed on auth_user because invitees are chosen before teams/players
    exist."""

    __tablename__ = "tournament_preview_access"
    __table_args__ = (
        UniqueConstraint("tournament_id", "auth_user_id", name="uq_tournament_preview_access_tournament_user"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True
    )
    auth_user_id: Mapped[int] = mapped_column(
        ForeignKey("auth.user.id", ondelete="CASCADE"), index=True
    )
```

- [ ] Add `from .preview_access import *` to `backend/shared/models/tournament/__init__.py` (after `from .tournament import *`). `models/__init__.py` re-exports the whole `tournament` package already — no change needed there.
- [ ] Commit: `feat(shared): add TournamentPreviewAccess allowlist model`

### Task 3: Model import test

**Files:** Create `backend/shared/tests/test_preview_access_model.py`

- [ ] Write test (pure, no DB — verifies mapping/table args):

```python
from shared.models.tournament import TournamentPreviewAccess
from shared.models.tournament.tournament import Tournament


def test_preview_access_table_and_schema():
    t = TournamentPreviewAccess.__table__
    assert t.schema == "tournament"
    assert t.name == "tournament_preview_access"
    cols = {c.name for c in t.columns}
    assert {"tournament_id", "auth_user_id", "id", "created_at", "updated_at"} <= cols
    # unique (tournament_id, auth_user_id)
    uqs = [c for c in t.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({col.name for col in uq.columns} == {"tournament_id", "auth_user_id"} for uq in uqs)


def test_tournament_is_hidden_column_default():
    col = Tournament.__table__.c.is_hidden
    assert col.nullable is False
    assert col.index is True
```

- [ ] Run: `cd backend && python -m pytest shared/tests/test_preview_access_model.py -v` — Expected: PASS (or SKIP-free PASS; no DB needed).
- [ ] Commit: `test(shared): TournamentPreviewAccess mapping`

### Task 4: Alembic migration

**Files:** Create `backend/migrations/versions/hidden0001_add_tournament_hidden_preview.py`

- [ ] Write (style mirrors `mvpimp0001`; head confirmed `mvpimp0001`):

```python
"""add hidden tournaments: Tournament.is_hidden + tournament_preview_access

Revision ID: hidden0001
Revises: mvpimp0001
"""

import sqlalchemy as sa
from alembic import op

revision = "hidden0001"
down_revision = "mvpimp0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("is_hidden", sa.Boolean(), server_default="false", nullable=False),
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_is_hidden", "tournament", ["is_hidden"], schema="tournament"
    )
    op.create_table(
        "tournament_preview_access",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", "auth_user_id", name="uq_tournament_preview_access_tournament_user"),
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_preview_access_tournament", "tournament_preview_access",
        ["tournament_id"], schema="tournament",
    )
    op.create_index(
        "ix_tournament_preview_access_auth_user", "tournament_preview_access",
        ["auth_user_id"], schema="tournament",
    )


def downgrade() -> None:
    op.drop_index("ix_tournament_preview_access_auth_user", table_name="tournament_preview_access", schema="tournament")
    op.drop_index("ix_tournament_preview_access_tournament", table_name="tournament_preview_access", schema="tournament")
    op.drop_table("tournament_preview_access", schema="tournament")
    op.drop_index("ix_tournament_is_hidden", table_name="tournament", schema="tournament")
    op.drop_column("tournament", "is_hidden", schema="tournament")
```

- [ ] Verify id column type matches existing (`TimeStampIntegerMixin` uses BigInteger PK — confirm against another `tournament`-schema table's migration; adjust if Integer).
- [ ] Verify single head after adding: `cd backend && python -m alembic heads` (or the static head-parser) shows only `hidden0001`.
- [ ] Commit: `feat(db): migration for is_hidden + tournament_preview_access`

---

## Phase 2 — Shared visibility service (+ unit tests)

### Task 5: Optional identity rehydration helper

**Files:** Modify `backend/shared/rpc/identity.py`

- [ ] Add (so both services share one non-raising rehydrator):

```python
def rehydrate_user_optional(identity: dict[str, Any] | None) -> AuthUser | None:
    """Like ``rehydrate_user`` but returns None for anonymous callers.

    The gateway injects ``identity`` only when a valid token is present on an
    AuthOptional route, so a falsy payload means anonymous — never an error.
    """
    if not identity:
        return None
    return rehydrate_user(identity)
```

- [ ] Add `"rehydrate_user_optional"` to `__all__`.
- [ ] Commit: `feat(shared): rehydrate_user_optional for AuthOptional reads`

### Task 6: `tournament_visibility` module — write failing unit tests first

**Files:** Create `backend/shared/tests/test_tournament_visibility.py`

- [ ] Write the full matrix test (pure, no DB — mirrors `test_auth_user_workspace_deny.py` style):

```python
from shared.models.identity.auth_user import AuthUser
from shared.models.tournament.tournament import Tournament
from shared.services.tournament_visibility import can_view_tournament


def _tournament(is_hidden: bool, workspace_id: int = 1) -> Tournament:
    t = Tournament()
    t.id = 100
    t.workspace_id = workspace_id
    t.is_hidden = is_hidden
    return t


def _user(user_id: int, *, superuser: bool = False, ws_admin: list[int] | None = None) -> AuthUser:
    u = AuthUser()
    u.id = user_id
    u.is_superuser = superuser
    u.is_active = True
    ws_rbac = {ws: {"roles": [], "permissions": [{"resource": "*", "action": "*"}]} for ws in (ws_admin or [])}
    u.set_rbac_cache(role_names=[], permissions=[], workspaces=[{"workspace_id": w} for w in (ws_admin or [])], workspace_rbac=ws_rbac)
    return u


def test_not_hidden_visible_to_everyone():
    assert can_view_tournament(None, _tournament(False), set()) is True
    assert can_view_tournament(_user(5), _tournament(False), set()) is True


def test_hidden_hidden_from_anonymous():
    assert can_view_tournament(None, _tournament(True), set()) is False


def test_hidden_visible_to_superuser():
    assert can_view_tournament(_user(5, superuser=True), _tournament(True), set()) is True


def test_hidden_visible_to_workspace_admin():
    assert can_view_tournament(_user(5, ws_admin=[1]), _tournament(True, workspace_id=1), set()) is True


def test_hidden_not_visible_to_admin_of_other_workspace():
    assert can_view_tournament(_user(5, ws_admin=[2]), _tournament(True, workspace_id=1), set()) is False


def test_hidden_visible_to_allowlisted_user():
    assert can_view_tournament(_user(7), _tournament(True), {7}) is True


def test_hidden_not_visible_to_non_allowlisted_logged_in_user():
    assert can_view_tournament(_user(9), _tournament(True), {7}) is False
```

- [ ] Run: `cd backend && python -m pytest shared/tests/test_tournament_visibility.py -v` — Expected: FAIL (module not found).

### Task 7: Implement `tournament_visibility`

**Files:** Create `backend/shared/services/tournament_visibility.py`

**Interfaces (later tasks rely on these exact names/signatures):**
- `async def load_preview_user_ids(session, tournament_id: int) -> set[int]`
- `def can_view_tournament(user: AuthUser | None, tournament: Tournament, preview_user_ids: set[int]) -> bool`
- `async def assert_tournament_viewable(session, user: AuthUser | None, tournament_id: int) -> Tournament` (raises `HTTPException(404)`)
- `def admin_visible_workspace_ids(user: AuthUser) -> list[int]`
- `def visible_tournaments_predicate(user: AuthUser | None) -> sa.ColumnElement[bool]`

- [ ] Implement:

```python
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.models.tournament.preview_access import TournamentPreviewAccess
from shared.models.tournament.tournament import Tournament

__all__ = (
    "load_preview_user_ids",
    "can_view_tournament",
    "assert_tournament_viewable",
    "admin_visible_workspace_ids",
    "visible_tournaments_predicate",
)


async def load_preview_user_ids(session: AsyncSession, tournament_id: int) -> set[int]:
    rows = await session.execute(
        sa.select(TournamentPreviewAccess.auth_user_id).where(
            TournamentPreviewAccess.tournament_id == tournament_id
        )
    )
    return {int(r) for r in rows.scalars().all()}


def can_view_tournament(
    user: AuthUser | None, tournament: Tournament, preview_user_ids: set[int]
) -> bool:
    if not tournament.is_hidden:
        return True
    if user is None:
        return False
    if user.is_workspace_admin(tournament.workspace_id):
        return True
    return int(user.id) in preview_user_ids


async def assert_tournament_viewable(
    session: AsyncSession, user: AuthUser | None, tournament_id: int
) -> Tournament:
    """Load the tournament and gate it. Raises 404 (never 403) when the viewer
    may not see it — including when it doesn't exist — to avoid disclosure."""
    tournament = await session.scalar(
        sa.select(Tournament).where(Tournament.id == tournament_id)
    )
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    if not tournament.is_hidden:
        return tournament
    preview_user_ids: set[int] = set()
    if user is not None and not user.is_workspace_admin(tournament.workspace_id):
        preview_user_ids = await load_preview_user_ids(session, tournament_id)
    if not can_view_tournament(user, tournament, preview_user_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


def admin_visible_workspace_ids(user: AuthUser) -> list[int]:
    """Workspaces (from the JWT cache) where the user has workspace-admin rights."""
    return [ws for ws in user.get_workspace_ids() if user.is_workspace_admin(ws)]


def visible_tournaments_predicate(user: AuthUser | None) -> sa.ColumnElement[bool]:
    """SQL predicate for list filtering. Apply to BOTH the page and count query."""
    if user is not None and user.is_superuser:
        return sa.true()
    clauses = [Tournament.is_hidden.is_(False)]
    if user is not None:
        admin_ws = admin_visible_workspace_ids(user)
        if admin_ws:
            clauses.append(Tournament.workspace_id.in_(admin_ws))
        clauses.append(
            Tournament.id.in_(
                sa.select(TournamentPreviewAccess.tournament_id).where(
                    TournamentPreviewAccess.auth_user_id == int(user.id)
                )
            )
        )
    return sa.or_(*clauses)
```

- [ ] Run: `cd backend && python -m pytest shared/tests/test_tournament_visibility.py -v` — Expected: PASS (all 8).
- [ ] Commit: `feat(shared): tournament_visibility guard + predicate + unit tests`

---

## Phase 3 — tournament-service enforcement (+ integration tests)

### Task 8: Expose `is_hidden` on the read model

**Files:** Modify `backend/tournament-service/src/schemas/tournament.py`, `backend/tournament-service/src/services/tournament/flows.py`

- [ ] In `TournamentRead` (schemas/tournament.py:33) add after `is_finished: bool`:
  ```python
    is_hidden: bool = False
  ```
- [ ] In `to_pydantic` (flows.py:108, the `schemas.TournamentRead(...)` call) add:
  ```python
        is_hidden=tournament.is_hidden,
  ```
- [ ] Commit: `feat(tournament): expose is_hidden on TournamentRead`

### Task 9: `is_hidden` editable via admin update schema

**Files:** Modify `backend/tournament-service/src/schemas/admin/tournament.py`

- [ ] Add to `TournamentUpdate` (line 36): `is_hidden: bool | None = None`
- [ ] Add to `TournamentCreate` (line 14): `is_hidden: bool = False`
- [ ] Note: the generic CRUD `update` (registry.py → `tournament_service.update_tournament`) already enqueues `structure_changed`, which invalidates `*tournaments/{id}*` (cache_invalidation.py:39-43). No extra invalidation code needed; the toggle path already purges the cached `get_read`.
- [ ] Commit: `feat(tournament): allow toggling is_hidden via admin update`

### Task 10: List filtering — thread viewer + predicate

**Files:** Modify `backend/tournament-service/src/services/tournament/service.py`, `backend/tournament-service/src/services/tournament/flows.py`, `backend/tournament-service/src/rpc/reads.py`

- [ ] `service.get_all` — add `visibility=None` param and apply it to both queries. Change signature to:
  ```python
  async def get_all(session, params, *, visibility: sa.ColumnElement[bool] | None = None):
  ```
  After the existing workspace filter (service.py:139), add:
  ```python
      if visibility is not None:
          query = query.where(visibility)
          total_query = total_query.where(visibility)
  ```
- [ ] `flows.get_all` — add `viewer` param and build the predicate:
  ```python
  from shared.services.tournament_visibility import visible_tournaments_predicate
  async def get_all(session, params, *, viewer=None):
      ...
      results, total = await service.get_all(session, params, visibility=visible_tournaments_predicate(viewer))
  ```
- [ ] `reads.py` `_list_tournaments` — rehydrate optional identity and pass it:
  ```python
  from shared.rpc.identity import rehydrate_user_optional
  ...
      async def op(session):
          qp = build_query_model(schemas.TournamentPaginationSortSearchQueryParams, data.get("query"))
          params = schemas.TournamentPaginationSortSearchParams.from_query_params(qp)
          viewer = rehydrate_user_optional(data.get("identity"))
          return await tournament_flows.get_all(session, params, viewer=viewer)
  ```
- [ ] Commit: `feat(tournament): filter hidden tournaments from list_tournaments`

### Task 11: Entity → tournament_id resolvers

**Files:** Create `backend/tournament-service/src/services/visibility_resolvers.py`

- [ ] Implement lightweight scalar resolvers (FK chains confirmed: Encounter.tournament_id, Team.tournament_id, EncounterMap.tournament_id, Match→Encounter.tournament_id):

```python
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import models


async def _scalar_or_404(session: AsyncSession, stmt, detail: str) -> int:
    val = await session.scalar(stmt)
    if val is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return int(val)


async def tournament_id_for_encounter(session: AsyncSession, encounter_id: int) -> int:
    return await _scalar_or_404(
        session,
        sa.select(models.Encounter.tournament_id).where(models.Encounter.id == encounter_id),
        "Encounter not found",
    )


async def tournament_id_for_team(session: AsyncSession, team_id: int) -> int:
    return await _scalar_or_404(
        session,
        sa.select(models.Team.tournament_id).where(models.Team.id == team_id),
        "Team not found",
    )


async def tournament_id_for_match(session: AsyncSession, match_id: int) -> int:
    return await _scalar_or_404(
        session,
        sa.select(models.Encounter.tournament_id)
        .join(models.Match, models.Match.encounter_id == models.Encounter.id)
        .where(models.Match.id == match_id),
        "Match not found",
    )
```

- [ ] Commit: `feat(tournament): entity->tournament_id resolvers for visibility gating`

### Task 12: Gate the public reads in `reads.py`

**Files:** Modify `backend/tournament-service/src/rpc/reads.py`

Add `from shared.rpc.identity import rehydrate_user_optional` and `from shared.services.tournament_visibility import assert_tournament_viewable` and `from src.services import visibility_resolvers`.

The pattern (gate BEFORE the cached/expensive read):
```python
viewer = rehydrate_user_optional(data.get("identity"))
await assert_tournament_viewable(session, viewer, <tournament_id>)
```

- [ ] `_get_tournament` — `await assert_tournament_viewable(session, viewer, _require_id(data))` before `get_read`.
- [ ] `_get_stages` — gate on `_require_id(data)`.
- [ ] `_get_standings` — gate on `_require_id(data)` (before/instead of the separate `get`).
- [ ] `_get_encounter` — resolve `tournament_id_for_encounter(session, _require_id(data))`, then gate.
- [ ] `_get_team` — resolve `tournament_id_for_team`, then gate.
- [ ] `_get_match` — resolve `tournament_id_for_match`, then gate.
- [ ] `_get_match_kill_feed` — resolve `tournament_id_for_match`, then gate.
- [ ] For the list handlers `_list_encounters`, `_list_matches`, `_list_teams`: these already accept `viewer_auth_user_id`/`workspace_id` and filter by tournament via query params. Where a `tournament_id` query param is present, gate it; where absent (cross-tournament lists), rely on the shared join-level filter — for this iteration, when the query includes `tournament_id`, call `assert_tournament_viewable` on it. Extract `tournament_id` from `_q1(data, "tournament_id", int)` and gate when not None.
- [ ] Commit: `feat(tournament): gate detail/nested reads on tournament visibility`

### Task 13: Gate public registration reads in `public_rpc.py`

**Files:** Modify `backend/tournament-service/src/rpc/public_rpc.py`

- [ ] `_reg_pub_form`, `_reg_pub_list` (currently anonymous, no identity): add `viewer = _optional_identity(data)` then `await assert_tournament_viewable(session, viewer, tournament_id)` before building the read.
- [ ] `_reg_pub_get_me` / `_reg_pub_update_me` / `_reg_pub_withdraw_me` / `_reg_pub_check_in` / `_reg_pub_create`: these already require identity (`_identity(data)`). Add `await assert_tournament_viewable(session, user, tournament_id)` after resolving `tournament_id` (a non-allowlisted, non-admin user must get 404 even on their own registration attempts against a hidden tournament).
- [ ] `_captain_map_pool` / `_captain_map_pool_state` / `_captain_veto` etc.: resolve tournament via `tournament_id_for_encounter` and gate (map-veto exposes bracket-adjacent data).
- [ ] Import `assert_tournament_viewable` and `visibility_resolvers`.
- [ ] Commit: `feat(tournament): gate public registration + captain reads on visibility`

### Task 14: Admin preview-access RPCs

**Files:** Modify `backend/tournament-service/src/rpc/admin_misc.py`

Add three subscribers gated by `is_workspace_admin` (per the issue). Resolve display data via identity where available; for v1 return `auth_user_id` plus best-effort user fields resolved from the shared `AuthUser`/player if cheaply available (a follow-up can enrich). Use existing helpers `_identity`, `get_tournament_workspace_id`.

- [ ] Add a small service module `backend/tournament-service/src/services/admin/preview_access.py`:
```python
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from shared.models.tournament.preview_access import TournamentPreviewAccess


async def list_preview_access(session, tournament_id: int):
    rows = await session.execute(
        sa.select(TournamentPreviewAccess).where(TournamentPreviewAccess.tournament_id == tournament_id)
        .order_by(TournamentPreviewAccess.created_at)
    )
    return list(rows.scalars().all())


async def add_preview_access(session, tournament_id: int, auth_user_id: int) -> TournamentPreviewAccess:
    existing = await session.scalar(
        sa.select(TournamentPreviewAccess).where(
            TournamentPreviewAccess.tournament_id == tournament_id,
            TournamentPreviewAccess.auth_user_id == auth_user_id,
        )
    )
    if existing is not None:
        return existing
    row = TournamentPreviewAccess(tournament_id=tournament_id, auth_user_id=auth_user_id)
    session.add(row)
    await session.commit()
    return row


async def remove_preview_access(session, tournament_id: int, auth_user_id: int) -> None:
    await session.execute(
        sa.delete(TournamentPreviewAccess).where(
            TournamentPreviewAccess.tournament_id == tournament_id,
            TournamentPreviewAccess.auth_user_id == auth_user_id,
        )
    )
    await session.commit()
```
- [ ] In `admin_misc.py`, add subscribers `rpc.tournament.preview_access_list|add|remove`. Each: `user = _identity(data)`; `tournament_id = _require_id(data)`; `ws_id = await auth.get_tournament_workspace_id(session, tournament_id)`; `if not user.is_workspace_admin(ws_id): raise HTTPException(403, ...)`. For add/remove read `auth_user_id` from `_payload(data)` (add) / path (`remove` via `_path_int(data, "auth_user_id")`). Serialize list entries as `{"id", "tournament_id", "auth_user_id", "created_at"}` (enrich with user display in a follow-up).
- [ ] After add/remove, invalidate the tournament read cache so the badge/state refresh: `from src.services.tournament.cache_invalidation import invalidate_tournament_cache` → `await invalidate_tournament_cache(tournament_id, "structure_changed")`.
- [ ] Commit: `feat(tournament): admin preview-access list/add/remove RPCs`

### Task 15: Integration tests (real-DB-with-skip pattern)

**Files:** Create `backend/tournament-service/tests/test_tournament_visibility_reads.py`

Mirror `test_registration_self_register_gate.py`: `_ensure_test_env`, `db_session` fixture (skip if DB down / refuse prod), uuid-suffixed workspace+tournament, `_authed_user(id, ws_admin=...)` helper, best-effort cleanup.

- [ ] Tests to write (call the flow/guard functions directly against the DB):
  - `assert_tournament_viewable`: not-hidden → returns; hidden + anon → 404; hidden + superuser → returns; hidden + allowlisted (insert a `TournamentPreviewAccess`) → returns; hidden + non-allowlisted user → 404.
  - `flows.get_all` list excludes a hidden tournament for an anonymous viewer but includes a non-hidden one; includes hidden for a superuser viewer.
- [ ] Run: `cd backend && python -m pytest tournament-service/tests/test_tournament_visibility_reads.py -v` — Expected: PASS or SKIP (if no dev DB). If skipped locally, note it in the summary.
- [ ] Commit: `test(tournament): visibility gating + list filtering`

### Task 16: Admin preview-access CRUD test

**Files:** Create `backend/tournament-service/tests/test_preview_access_admin.py`

- [ ] DB-backed: add → list shows the entry; add same again → idempotent (still one); remove → list empty; non-admin actor → 403. Follow the skip pattern.
- [ ] Run: `cd backend && python -m pytest tournament-service/tests/test_preview_access_admin.py -v` — Expected: PASS/SKIP.
- [ ] Commit: `test(tournament): admin preview-access CRUD`

---

## Phase 4 — gateway (auth flips, admin routes, WS ACL)

### Task 17: Flip tournament read routes to AuthOptional + add admin routes

**Files:** Modify `gateway/internal/tournament/routes.go`, `gateway/internal/tournament/admin_misc_routes.go`

- [ ] In `routes.go` change `Auth: edge.AuthNone` → `Auth: edge.AuthOptional` for: `/api/v1/tournaments` (list), `/api/v1/tournaments/{id}`, `.../stages`, `.../standings`, `/api/v1/matches`, `/api/v1/matches/{id}`, `/api/v1/matches/{id}/kill-feed`, `/api/v1/teams`, `/api/v1/teams/{id}`, `/api/v1/encounters/{id}`. (`/api/v1/encounters` + `/overview` are already AuthOptional.) Leave `lookup`/`statistics/*`/`league/*` as AuthNone (workspace-scoped aggregates, not single-tournament — out of scope for per-tournament 404; hidden tournaments are already excluded from these via the shared list/query filter where applicable — verify statistics flows exclude hidden in a follow-up if needed).
- [ ] In `admin_misc_routes.go` add to `AdminMiscRoutes`:
```go
	// preview access allowlist (workspace-admin gated in the worker)
	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{tournament_id}/preview-access", Queue: "rpc.tournament.preview_access_list", IDParam: "tournament_id", Auth: edge.AuthRequired},
	{Method: "POST", Pattern: "/api/v1/admin/tournaments/{tournament_id}/preview-access", Queue: "rpc.tournament.preview_access_add", IDParam: "tournament_id", Body: true, Auth: edge.AuthRequired},
	{Method: "DELETE", Pattern: "/api/v1/admin/tournaments/{tournament_id}/preview-access/{auth_user_id}", Queue: "rpc.tournament.preview_access_remove", IDParam: "tournament_id", Path: []string{"auth_user_id"}, Auth: edge.AuthRequired, Success: 204},
```
- [ ] Build: `cd gateway && go build ./...` — Expected: OK.
- [ ] Commit: `feat(gateway): AuthOptional tournament reads + preview-access admin routes`

### Task 18: Flip app-service tournament-scoped read routes to AuthOptional

**Files:** Modify `gateway/internal/app/routes.go`, `gateway/internal/app/achievements_routes.go`

- [ ] In `routes.go` flip to `AuthOptional` the tournament-scoped reads: `heroes/statistics/playtime`, `heroes/{hero_id}/leaderboard`, `statistics/dashboard`, `users/{id}/compare`, `users/{id}/compare/heroes`, `users/{id}/tournaments`, `users/{id}/tournaments/{tournament_id}`, `users/{id}/tournaments/{tournament_id}/leaderboard`, `users/{id}/maps`, `users/{id}/maps/summary`, `users/{id}/heroes`. (These are the tournament-scoped reads from the app-service audit; identity must reach the worker so it can gate.)
- [ ] In `achievements_routes.go` flip `/api/v1/achievements/user/{user_id}` to `AuthOptional`.
- [ ] Build: `cd gateway && go build ./...` — Expected: OK.
- [ ] Commit: `feat(gateway): AuthOptional for tournament-scoped app-service reads`

### Task 19: WS ACL visibility gate

**Files:** Modify `gateway/internal/workspace/workspace.go`, `gateway/internal/acl/acl.go`, `gateway/internal/acl/acl_test.go`

- [ ] `workspace.go` — add SQL + methods (short TTL cache like the others):
```go
const (
    tournamentHiddenSQL   = `SELECT is_hidden FROM tournament.tournament WHERE id = $1`
    previewAllowedSQL     = `SELECT EXISTS(SELECT 1 FROM tournament.tournament_preview_access WHERE tournament_id = $1 AND auth_user_id = $2)`
    encounterTournamentSQL = `SELECT tournament_id FROM tournament.encounter WHERE id = $1`
)
// TournamentIsHidden(ctx, tournamentID) (hidden bool, found bool, err error)
// IsPreviewAllowed(ctx, userID, tournamentID) (bool, error)
// EncounterTournamentID(ctx, encounterID) (int64, bool, error)
```
  Add matching ttlCaches. (TournamentWorkspaceID already exists for the member check.)
- [ ] `acl.go` — extend the `WorkspaceResolver`/checker interfaces (or add a new `VisibilityChecker` interface with the three methods) and wire it. Replace the three `allowPublic` registrations for `tournament:*:bracket`, `tournament:*:draft`, `encounter:*:map-veto` with a `allowSpectate` check:
```go
// allowSpectate: public unless the tournament is hidden; hidden tournaments
// require a logged-in insider (superuser OR workspace member OR preview-allowlisted).
// NOTE: the edge User carries only ID+IsSuperuser, so we use workspace MEMBER
// (not strictly admin) as the closest available insider check — consistent with
// allowBalancer. Outsiders (anon / non-member / non-allowlisted) are always denied.
```
  For `encounter:*:map-veto`, resolve tournamentID via `EncounterTournamentID` first.
- [ ] `main.go` — `acl.New(wsStore, wsStore)` already passes the store twice; if you added a third interface, pass `wsStore` again (it satisfies all). Update `acl.New` signature accordingly.
- [ ] `acl_test.go` — add cases: hidden tournament + anon → deny; + superuser → allow; + member → allow; + preview-allowed → allow; + outsider → deny; not-hidden → allow (public). Use fakes for the new interface.
- [ ] Build + test: `cd gateway && go build ./... && go test ./internal/acl/... ./internal/workspace/...` — Expected: OK/PASS.
- [ ] Commit: `feat(gateway): gate WS tournament topics on hidden visibility`

---

## Phase 5 — app-service enforcement (+ tests)

### Task 20: Gate tournament-scoped app-service reads

**Files:** Modify `backend/app-service/src/rpc/users.py`, `heroes.py`, `achievements.py`, `statistics.py` (+ `src/rpc/_common.py` if a helper is added)

The guard (identity is now injected by the gateway on these routes):
```python
from shared.rpc.identity import rehydrate_user_optional
from shared.services.tournament_visibility import assert_tournament_viewable
...
viewer = rehydrate_user_optional(data.get("identity"))
await assert_tournament_viewable(session, viewer, tournament_id)
```
Add the guard inside each handler's `op(session)` BEFORE building results, using the tournament_id source the audit identified:

- [ ] `users.py` `_tournament` (top-level `data["tournament_id"]`), `_tournament_leaderboard` (top-level), `_heroes` (query), `_maps` (query via params), `_maps_summary` (query), `_compare` (query), `_compare_heroes` (query). For query-sourced ids, gate only when the id is present (`if tournament_id is not None`).
- [ ] `heroes.py` `_playtime` (query), `_leaderboard` (query).
- [ ] `achievements.py` `_user` (query `tournament_id`, gate when present).
- [ ] `statistics.py` `_dashboard` — resolve the active tournament(s) it returns and drop any hidden one the viewer can't see (filter the returned `DashboardActiveTournamentStats` by `can_view_tournament`; or gate each resolved tournament_id). Simplest correct approach: after building the dashboard, filter out entries whose tournament fails `assert`-style check; implement with `can_view_tournament` + `load_preview_user_ids` to avoid raising (dashboard is a workspace-level read, not a single-tournament 404).
- [ ] `users.py` `_tournaments` (a user's tournaments list, cached) — exclude hidden tournaments the viewer can't see at the QUERY level in the underlying flow (`user/flows.py get_tournaments`). Because this read is cashews-cached WITHOUT the viewer, either (a) bypass cache when a viewer is present and any hidden tournament exists, or (b) simplest: filter hidden tournaments out of the base query unconditionally for anonymous, and add the viewer's visible set — since the cache key lacks the viewer, the safe v1 is to always exclude hidden here (a hidden tournament shouldn't appear in a public "user's tournaments" list even to admins; they see it via the tournament pages). Document the choice. Prefer: exclude `is_hidden = true` in the query feeding this list.
- [ ] Commit: `feat(app): gate tournament-scoped reads on visibility`

### Task 21: app-service tests

**Files:** Create `backend/app-service/tests/test_tournament_visibility_reads.py`

- [ ] DB-backed (skip pattern): a hidden tournament read (`get_tournament_with_stats` / the leaderboard flow) returns 404 for anon and non-allowlisted, returns data for superuser; `get_tournaments` list excludes the hidden one. Reuse app-service `tests/conftest.py` DB fixtures if present; else mirror the tournament-service skip fixture.
- [ ] Run: `cd backend && python -m pytest app-service/tests/test_tournament_visibility_reads.py -v` — Expected PASS/SKIP.
- [ ] Commit: `test(app): tournament visibility gating`

---

## Phase 6 — frontend

### Task 22: Types + admin API

**Files:** Modify `frontend/src/types/tournament.types.ts`, `frontend/src/types/admin.types.ts`, `frontend/src/services/admin.service.ts`

- [ ] Add `is_hidden?: boolean` to the `Tournament` type and `is_hidden?: boolean` to `TournamentUpdateInput`.
- [ ] Add a `PreviewAccessEntry` type: `{ id: number; tournament_id: number; auth_user_id: number; created_at: string; user?: { id: number; name: string; avatar_url?: string | null } }`.
- [ ] Add to `AdminService`:
```ts
async getTournamentPreviewAccess(id: number): Promise<PreviewAccessEntry[]> {
  const r = await apiFetch(`/api/v1/admin/tournaments/${id}/preview-access`);
  return r.json();
}
async addTournamentPreviewUser(id: number, authUserId: number): Promise<PreviewAccessEntry> {
  const r = await apiFetch(`/api/v1/admin/tournaments/${id}/preview-access`, { method: "POST", body: { auth_user_id: authUserId } });
  return r.json();
}
async removeTournamentPreviewUser(id: number, authUserId: number): Promise<void> {
  await apiFetch(`/api/v1/admin/tournaments/${id}/preview-access/${authUserId}`, { method: "DELETE" });
}
```
- [ ] Verify: `cd frontend && bunx tsc --noEmit` — Expected: no new errors.
- [ ] Commit: `feat(frontend): types + admin API for hidden tournaments`

### Task 23: Admin Visibility section

**Files:** Modify `frontend/src/app/admin/tournaments/[id]/components/tournamentWorkspace.helpers.ts`, `frontend/src/app/admin/tournaments/[id]/components/TournamentSettingsTab.tsx`

- [ ] `tournamentWorkspace.helpers.ts` — add `is_hidden: boolean` to `TournamentFormState`; set it in `getTournamentForm()` from `tournament.is_hidden ?? false`.
- [ ] `TournamentSettingsTab.tsx` — add a new `<Card>` "Visibility" mirroring the existing checkbox panel (line ~379): a `Checkbox` bound to `form.is_hidden`. Include `is_hidden` in the `handleSubmit` payload. When `form.is_hidden` is true, render the allowlist editor below it: `UserSearchCombobox` (from `components/admin/UserSearchCombobox.tsx`) to add users, and a list of current entries (from `getTournamentPreviewAccess`) with per-row remove buttons — model the add/remove mutations on `admin/workspaces/members/page.tsx`. Invalidate the preview-access query after add/remove. Admin UI stays English (matches existing admin strings).
- [ ] Verify: `cd frontend && bunx tsc --noEmit && bun run lint` (or `bunx eslint`) — Expected: clean.
- [ ] Commit: `feat(frontend): admin Visibility section + preview allowlist editor`

### Task 24: Public badge + preview banner + i18n

**Files:** Modify `frontend/src/app/(site)/tournaments/components/TournamentsTable.tsx`, `frontend/src/app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx`, `frontend/src/i18n/messages/en.json`, `frontend/src/i18n/messages/ru.json`

- [ ] i18n: add `common.previewBadge` ("Hidden" / "Скрыт") and `tournamentDetail.previewBanner` ("Preview — hidden from the public site" / "Предпросмотр — скрыт от публичного сайта"). Keep EN+RU parity (the `messages.parity.test.ts` requires identical key trees). No `{placeholder}` in these unless values are passed.
- [ ] `TournamentsTable.tsx` — in the name cell (~line 43), when `tournament.is_hidden`, render a pill/badge with `t("common.previewBadge")` next to the live pill.
- [ ] `TournamentClientLayout.tsx` — when `tournament?.is_hidden`, render a banner above `<PageHero>` (inside the `.aqt-tn` wrapper) with `t("tournamentDetail.previewBanner")`.
- [ ] Verify: `cd frontend && bunx tsc --noEmit && bun test src/i18n/messages.parity.test.ts` — Expected: clean/PASS.
- [ ] Commit: `feat(frontend): hidden badge + preview banner + i18n`

---

## Phase 7 — verification + PR

### Task 25: Full verification

- [ ] Backend touched packages: `cd backend && python -m pytest shared/tests -q` and the tournament-service + app-service visibility tests (note any DB skips).
- [ ] Lint backend: `rtk ruff check backend/shared backend/tournament-service/src backend/app-service/src` (or `python -m ruff check ...`).
- [ ] Gateway: `cd gateway && go build ./... && go vet ./... && go test ./...`.
- [ ] Frontend: `cd frontend && bunx tsc --noEmit && bun run lint && bun test src/i18n/messages.parity.test.ts`.
- [ ] Re-read the acceptance criteria in issue #115 and tick each against a test or code path.

### Task 26: PR-ready summary
- [ ] Ensure the branch is coherent (rebase/squash not required). Do NOT push without approval.
- [ ] Write a summary of what a deploy requires: run migration `hidden0001`; rebuild tournament-service + app-service + gateway; restart nginx (prod redeploy requirement); flush tournament read caches (`*tournaments/*`).

---

## Self-Review notes (checked against spec)

- **Spec coverage:** is_hidden col (T1), preview table (T2), migration (T4), visibility module with all four functions (T7), list filtering at query level (T10), tournament-service detail/nested/registration gating (T12/T13), gateway auth flips + admin routes (T17/T18), app-service audit-driven gating incl. the leak-prone paths (T20), WS ACL (T19), admin toggle + allowlist RPCs (T9/T14) + frontend (T22-24), tests (T3/T6/T15/T16/T21 + gateway T19). Cache gotcha handled by gate-before-cached-read (T12) and existing structure_changed invalidation (T9).
- **Known simplifications (documented, not gaps):** WS gate uses workspace MEMBER not strictly ADMIN (edge User lacks RBAC); `users.tournaments` list unconditionally excludes hidden (cache keyed without viewer); statistics/league aggregates not per-tournament-404'd (they aggregate; hidden exclusion is a follow-up if a leak is shown). Preview-access list returns ids in v1; user-display enrichment is a follow-up.
