# Workspace Subdomains (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve each opted-in workspace at its own subdomain `{subdomain}.owt.craazzzyyfoxx.me` as a white-label site (host = workspace), with OAuth, SSO across subdomains, and per-workspace SEO working end-to-end.

**Architecture:** A Next.js `middleware.ts` resolves the request host → workspace via a new cached `rpc.app.workspaces.by_host` and injects `x-owt-workspace-id` (host beats cookie). OAuth funnels through one registered apex callback carrying the origin in a signed HMAC state; session cookies are set `Domain=.owt.craazzzyyfoxx.me` so login carries across all subdomains. Metadata becomes per-request per-workspace.

**Tech Stack:** Python 3 (FastStream RPC, SQLAlchemy, Alembic, Pydantic v2, pytest) · Next.js App Router (TypeScript, `bun test`) · Go gateway (`go test`).

**Spec:** `docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md`. This plan is **Phase 1 only** (subdomains). Phase 2 (custom domains, SSO ticket handoff, on-demand TLS) gets its own plan.

## Global Constraints

- Platform zone: `owt.craazzzyyfoxx.me`. Apex + `www` = multi-workspace platform. `{label}.owt.craazzzyyfoxx.me` = tenant (white-label) host.
- Subdomain label rule: `^[a-z0-9-]+$`, length 1–63, not in the reserved set: `www api auth admin app assets static cdn mail ws`.
- Session cookies: written under `owt_*` names, read as `owt_* ?? aqt_*` (compat, no forced logout). Session cookies get `Domain=.owt.craazzzyyfoxx.me`.
- Single OAuth callback (all providers, all origins): `https://owt.craazzzyyfoxx.me/auth/callback`.
- White-label lock: on a tenant host, `x-owt-workspace-id` overrides the `owt-workspace-id` cookie; switcher + "communities" hidden.
- Typed columns only (no JSON bags). Follow existing patterns (branding shipped the same way — [[project_workspace_branding]]).
- Lint/format: Python `ruff`/`black` via `uv run`; TS `eslint`; Go `gofmt`/`go vet`. Tests: `uv run pytest`, `bun test <path>`, `go test`.

---

### Task 1: Hostname / subdomain utility (backend, shared)

**Files:**
- Create: `backend/shared/tenancy/hostnames.py`
- Create: `backend/shared/tenancy/__init__.py` (if missing — check first; `Workspace` already lives in `backend/shared/models/tenancy/`, but `shared/tenancy/` as a non-model package is new)
- Test: `backend/app-service/tests/test_hostnames.py`

**Interfaces:**
- Produces:
  - `PLATFORM_ZONE: str = "owt.craazzzyyfoxx.me"`
  - `RESERVED_SUBDOMAINS: frozenset[str]`
  - `validate_subdomain_label(label: str) -> str` — normalizes (lower/strip) and returns it, raises `ValueError` on invalid/reserved.
  - `subdomain_from_host(host: str) -> str | None` — returns the label if `host` is `{label}.{PLATFORM_ZONE}` and label is a single segment (not the apex/`www`), else `None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/app-service/tests/test_hostnames.py
import pytest

from shared.tenancy.hostnames import (
    PLATFORM_ZONE,
    subdomain_from_host,
    validate_subdomain_label,
)


def test_platform_zone():
    assert PLATFORM_ZONE == "owt.craazzzyyfoxx.me"


@pytest.mark.parametrize("label", ["team-a", "owcs", "a", "x1y2"])
def test_validate_accepts_valid_labels(label):
    assert validate_subdomain_label(label.upper()) == label  # normalizes case


@pytest.mark.parametrize("bad", ["team_a", "-team", "te am", "", "a" * 64, "café"])
def test_validate_rejects_malformed(bad):
    with pytest.raises(ValueError):
        validate_subdomain_label(bad)


@pytest.mark.parametrize("reserved", ["www", "api", "auth", "admin", "ws"])
def test_validate_rejects_reserved(reserved):
    with pytest.raises(ValueError):
        validate_subdomain_label(reserved)


def test_subdomain_from_host_extracts_label():
    assert subdomain_from_host("team-a.owt.craazzzyyfoxx.me") == "team-a"
    assert subdomain_from_host("TEAM-A.owt.craazzzyyfoxx.me") == "team-a"


def test_subdomain_from_host_ignores_apex_www_and_foreign():
    assert subdomain_from_host("owt.craazzzyyfoxx.me") is None
    assert subdomain_from_host("www.owt.craazzzyyfoxx.me") is None
    assert subdomain_from_host("a.b.owt.craazzzyyfoxx.me") is None  # multi-segment
    assert subdomain_from_host("evil.com") is None
    assert subdomain_from_host("team-a.owt.craazzzyyfoxx.me:443") == "team-a"  # port stripped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app-service && uv run pytest tests/test_hostnames.py -q`
Expected: FAIL — `ModuleNotFoundError: shared.tenancy.hostnames`

- [ ] **Step 3: Write the implementation**

```python
# backend/shared/tenancy/hostnames.py
"""Platform-zone hostname helpers for host->workspace resolution.

Phase 1 handles subdomains under the platform zone. Custom domains (Phase 2)
match a separate column and are resolved elsewhere.
"""

from __future__ import annotations

import re

__all__ = (
    "PLATFORM_ZONE",
    "RESERVED_SUBDOMAINS",
    "validate_subdomain_label",
    "subdomain_from_host",
)

PLATFORM_ZONE = "owt.craazzzyyfoxx.me"

RESERVED_SUBDOMAINS = frozenset(
    {"www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws"}
)

_LABEL_RE = re.compile(r"^[a-z0-9-]+$")


def validate_subdomain_label(label: str) -> str:
    normalized = label.strip().lower()
    if not (1 <= len(normalized) <= 63):
        raise ValueError("Subdomain must be 1-63 characters")
    if not _LABEL_RE.fullmatch(normalized):
        raise ValueError("Subdomain may contain only a-z, 0-9 and hyphen")
    if normalized.startswith("-") or normalized.endswith("-"):
        raise ValueError("Subdomain may not start or end with a hyphen")
    if normalized in RESERVED_SUBDOMAINS:
        raise ValueError(f"Subdomain '{normalized}' is reserved")
    return normalized


def subdomain_from_host(host: str) -> str | None:
    if not host:
        return None
    hostname = host.strip().lower().split(":", 1)[0]  # drop port
    suffix = "." + PLATFORM_ZONE
    if not hostname.endswith(suffix):
        return None
    label = hostname[: -len(suffix)]
    if not label or "." in label:  # apex has empty label; multi-segment rejected
        return None
    if label == "www" or label in RESERVED_SUBDOMAINS:
        return None
    return label
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend/app-service && uv run pytest tests/test_hostnames.py -q`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
cd backend && uv run ruff check shared/tenancy/hostnames.py && uv run ruff format shared/tenancy/hostnames.py
git add backend/shared/tenancy/ backend/app-service/tests/test_hostnames.py
git commit -m "feat(tenancy): add platform-zone hostname + subdomain-label helpers"
```

---

### Task 2: Workspace columns + migration

**Files:**
- Modify: `backend/shared/models/tenancy/workspace.py` (add columns after `is_active`/branding block)
- Create: `backend/migrations/versions/wsdomain0001_add_workspace_subdomain_seo.py`

**Interfaces:**
- Produces `Workspace.subdomain`, `Workspace.seo_title`, `Workspace.seo_description` (all `Mapped[str | None]`), `subdomain` uniquely indexed.

- [ ] **Step 1: Confirm the current alembic head**

Run:
```bash
cd backend/migrations/versions && python - <<'PY'
import re, pathlib
revs, downs = {}, set()
for p in pathlib.Path('.').glob('*.py'):
    t = p.read_text(encoding='utf-8', errors='ignore')
    rm = re.search(r'^revision(?::\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', t, re.M)
    if rm: revs[rm.group(1)] = p.name
    m = re.search(r'^down_revision\b[^=]*=\s*', t, re.M)
    if m:
        rest = t[m.end():]
        seg = rest[:rest.index(')')+1] if rest.lstrip().startswith('(') else rest.split('\n',1)[0]
        downs.update(re.findall(r'["\']([^"\']+)["\']', seg))
print("HEADS:", [r for r in revs if r not in downs])
PY
```
Expected: `HEADS: ['wsbrand0001']` (the branding migration). If different, use the printed head as `down_revision`.

- [ ] **Step 2: Add the model columns**

In `backend/shared/models/tenancy/workspace.py`, after the `brand_surface` column, add:

```python
    # White-label multi-domain (Phase 1: subdomains). See
    # docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md.
    subdomain: Mapped[str | None] = mapped_column(String(63), unique=True, index=True, nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(), nullable=True)
```

- [ ] **Step 3: Write the migration**

```python
# backend/migrations/versions/wsdomain0001_add_workspace_subdomain_seo.py
"""add workspace subdomain + seo columns

Revision ID: wsdomain0001
Revises: wsbrand0001
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsdomain0001"
down_revision: str | None = "wsbrand0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("subdomain", sa.String(length=63), nullable=True))
    op.add_column("workspace", sa.Column("seo_title", sa.String(), nullable=True))
    op.add_column("workspace", sa.Column("seo_description", sa.String(), nullable=True))
    op.create_index("ix_workspace_subdomain", "workspace", ["subdomain"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_workspace_subdomain", table_name="workspace")
    op.drop_column("workspace", "seo_description")
    op.drop_column("workspace", "seo_title")
    op.drop_column("workspace", "subdomain")
```

- [ ] **Step 4: Verify the migration renders offline**

Run: `cd backend/app-service && uv run alembic upgrade wsbrand0001:wsdomain0001 --sql`
Expected: prints `ALTER TABLE workspace ADD COLUMN subdomain ...` + the unique index, no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/shared/models/tenancy/workspace.py backend/migrations/versions/wsdomain0001_add_workspace_subdomain_seo.py
git commit -m "feat(workspace): add subdomain + seo columns"
```

---

### Task 3: Schemas + frontend type

**Files:**
- Modify: `backend/app-service/src/schemas/workspace.py` (`WorkspaceRead`, `WorkspaceUpdate`)
- Modify: `frontend/src/types/workspace.types.ts` (`Workspace`)
- Test: `backend/app-service/tests/test_workspace_branding_schema.py` (extend the existing file)

**Interfaces:**
- Consumes: `validate_subdomain_label` (Task 1).
- Produces: `WorkspaceRead.{subdomain,seo_title,seo_description}`, `WorkspaceUpdate.{subdomain,seo_title,seo_description}` with subdomain validated.

- [ ] **Step 1: Write the failing test** (append to `test_workspace_branding_schema.py`)

```python
def test_update_accepts_valid_subdomain():
    model = schemas.WorkspaceUpdate(subdomain="Team-A")
    assert model.subdomain == "team-a"  # normalized


@pytest.mark.parametrize("bad", ["team_a", "www", "-x", "a" * 64])
def test_update_rejects_bad_subdomain(bad):
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(subdomain=bad)


def test_read_exposes_domain_seo_fields():
    fields = schemas.WorkspaceRead.model_fields
    for name in ("subdomain", "seo_title", "seo_description"):
        assert name in fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app-service && uv run pytest tests/test_workspace_branding_schema.py -q`
Expected: FAIL — `WorkspaceUpdate` has no `subdomain`.

- [ ] **Step 3: Implement the schema changes**

In `backend/app-service/src/schemas/workspace.py`, add imports + fields:

```python
from pydantic import field_validator

from shared.tenancy.hostnames import validate_subdomain_label
```

In `WorkspaceRead` (after branding fields):

```python
    subdomain: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
```

In `WorkspaceUpdate` (after branding fields):

```python
    subdomain: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None

    @field_validator("subdomain")
    @classmethod
    def _validate_subdomain(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return validate_subdomain_label(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend/app-service && uv run pytest tests/test_workspace_branding_schema.py -q`
Expected: PASS

- [ ] **Step 5: Update the frontend type**

In `frontend/src/types/workspace.types.ts`, add to `interface Workspace` (after branding fields):

```typescript
  subdomain: string | null;
  seo_title: string | null;
  seo_description: string | null;
```

- [ ] **Step 6: Commit**

```bash
git add backend/app-service/src/schemas/workspace.py backend/app-service/tests/test_workspace_branding_schema.py frontend/src/types/workspace.types.ts
git commit -m "feat(workspace): expose subdomain + seo in schemas and frontend type"
```

---

### Task 4: `get_by_subdomain` service + `by_host` RPC

**Files:**
- Modify: `backend/app-service/src/services/workspace/service.py` (add `get_by_subdomain`)
- Modify: `backend/shared/repository` workspace repo (add `get_by_subdomain` mirroring `get_by_slug`) — locate via `grep -rn "def get_by_slug" backend/shared/repository`
- Modify: `backend/app-service/src/rpc/workspaces.py` (add `by_host` subscriber)
- Test: `backend/app-service/tests/api/test_workspaces_by_host.py` (integration, DB-gated like existing `rpc` tests)

**Interfaces:**
- Consumes: `subdomain_from_host` (Task 1), `Workspace.subdomain` (Task 2).
- Produces: `service.get_by_subdomain(session, label) -> Workspace | None`; RPC topic `rpc.app.workspaces.by_host` accepting `{query: {host: [str]}}`, returning envelope `{ok, data: {workspace_id, slug} | None}`.

- [ ] **Step 1: Add the repository + service lookup**

In the workspace repository (next to `get_by_slug`):

```python
    async def get_by_subdomain(self, session: AsyncSession, subdomain: str) -> Workspace | None:
        result = await session.execute(select(Workspace).where(Workspace.subdomain == subdomain))
        return result.scalar_one_or_none()
```

In `backend/app-service/src/services/workspace/service.py` (next to `get_by_slug`):

```python
async def get_by_subdomain(session: AsyncSession, subdomain: str) -> models.Workspace | None:
    return await _workspace_repo.get_by_subdomain(session, subdomain)
```

- [ ] **Step 2: Add the `by_host` RPC handler**

In `backend/app-service/src/rpc/workspaces.py`, inside `register(broker, logger)` (near the existing public `list`/`get` handlers), add:

```python
    @broker.subscriber("rpc.app.workspaces.by_host")
    async def by_host(data: dict, msg: RabbitMessage) -> dict:
        # Public, cached: host -> {workspace_id, slug}. Phase 1 matches the
        # platform-zone subdomain only; custom domains are Phase 2.
        host = _first_query(data, "host")  # existing helper for query params
        if not host:
            return {"ok": True, "data": None}
        label = subdomain_from_host(host)
        if label is None:
            return {"ok": True, "data": None}
        async with db.async_session_maker() as session:
            workspace = await workspace_service.get_by_subdomain(session, label)
        if workspace is None:
            return {"ok": True, "data": None}
        return {"ok": True, "data": {"workspace_id": workspace.id, "slug": workspace.slug}}
```

Add imports at the top of the module: `from shared.tenancy.hostnames import subdomain_from_host`. Reuse the module's existing query-extraction helper; if none exists, read `data.get("query", {}).get("host", [None])[0]`.

- [ ] **Step 3: Expose the route through the gateway**

Add a `RouteSpec` for `GET /api/v1/workspaces/by-host` → `rpc.app.workspaces.by_host` in the gateway route table (find the workspace routes: `grep -rn "workspaces" gateway/internal/*/`). Follow the existing public workspace `list` route (no auth). Map query `host`.

- [ ] **Step 4: Write the integration test**

```python
# backend/app-service/tests/api/test_workspaces_by_host.py
import pytest

from src.rpc import workspaces as workspaces_rpc


@pytest.mark.integration
def test_by_host_unknown_returns_null(rpc):
    harness = rpc  # session-scoped harness (skips if DB unreachable)
    harness.register(workspaces_rpc)
    res = harness.call_sync(
        "rpc.app.workspaces.by_host",
        {"query": {"host": ["nope.owt.craazzzyyfoxx.me"]}},
    )
    assert res["ok"] is True
    assert res["data"] is None
```

(Full round-trip with a seeded subdomain is exercised in E2E; the unit of resolution logic is covered by Task 1.)

- [ ] **Step 5: Run + commit**

Run: `cd backend/app-service && uv run pytest tests/api/test_workspaces_by_host.py -q` (skips cleanly without a DB).

```bash
git add backend/shared/repository backend/app-service/src/services/workspace/service.py backend/app-service/src/rpc/workspaces.py backend/app-service/tests/api/test_workspaces_by_host.py gateway/
git commit -m "feat(workspace): add by_host resolver (subdomain) rpc + route"
```

---

### Task 5: Frontend host parsing utility

**Files:**
- Create: `frontend/src/lib/host.ts`
- Test: `frontend/src/lib/host.test.ts`

**Interfaces:**
- Produces:
  - `PLATFORM_ZONE = "owt.craazzzyyfoxx.me"`
  - `type HostResolution = { mode: "platform" } | { mode: "tenant"; subdomain: string }`
  - `resolveHost(host: string | null | undefined): HostResolution` — apex/`www`/empty → platform; `{label}.PLATFORM_ZONE` (single segment, non-reserved) → tenant; anything else (foreign host in dev, multi-segment) → platform (safe default; middleware treats "no workspace found" as 404 only after a lookup miss).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/host.test.ts
import { describe, expect, it } from "bun:test";
import { PLATFORM_ZONE, resolveHost } from "@/lib/host";

describe("resolveHost", () => {
  it("treats apex + www as platform", () => {
    expect(resolveHost(PLATFORM_ZONE)).toEqual({ mode: "platform" });
    expect(resolveHost(`www.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost(null)).toEqual({ mode: "platform" });
  });

  it("extracts a tenant subdomain", () => {
    expect(resolveHost(`team-a.${PLATFORM_ZONE}`)).toEqual({ mode: "tenant", subdomain: "team-a" });
    expect(resolveHost(`TEAM-A.${PLATFORM_ZONE}:443`)).toEqual({ mode: "tenant", subdomain: "team-a" });
  });

  it("rejects reserved + multi-segment labels as platform", () => {
    expect(resolveHost(`api.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost(`a.b.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && bun test src/lib/host.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/lib/host.ts
export const PLATFORM_ZONE = "owt.craazzzyyfoxx.me";

const RESERVED = new Set([
  "www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws",
]);

export type HostResolution = { mode: "platform" } | { mode: "tenant"; subdomain: string };

export function resolveHost(host: string | null | undefined): HostResolution {
  if (!host) return { mode: "platform" };
  const hostname = host.trim().toLowerCase().split(":")[0];
  const suffix = `.${PLATFORM_ZONE}`;
  if (!hostname.endsWith(suffix)) return { mode: "platform" };
  const label = hostname.slice(0, -suffix.length);
  if (!label || label.includes(".") || RESERVED.has(label)) return { mode: "platform" };
  return { mode: "tenant", subdomain: label };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && bun test src/lib/host.test.ts`
Expected: PASS (4 assertions)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/host.ts frontend/src/lib/host.test.ts
git commit -m "feat(host): add platform-zone host resolver"
```

---

### Task 6: `getByHost` service + Next.js middleware

**Files:**
- Modify: `frontend/src/services/workspace.service.ts` (add `getByHost`)
- Create: `frontend/src/middleware.ts`

**Interfaces:**
- Consumes: `resolveHost` (Task 5), `by-host` route (Task 4).
- Produces: request header `x-owt-workspace-id` on tenant hosts; the `x-owt-host-mode` header (`platform` | `tenant`) for downstream server components.

- [ ] **Step 1: Add the service method**

In `frontend/src/services/workspace.service.ts`:

```typescript
  static async getByHost(host: string): Promise<{ workspace_id: number; slug: string } | null> {
    const res = await apiFetch(`/api/v1/workspaces/by-host`, {
      query: { host },
      skipWorkspace: true,
    });
    return res.json();
  }
```

- [ ] **Step 2: Write the middleware**

```typescript
// frontend/src/middleware.ts
import { NextRequest, NextResponse } from "next/server";
import { resolveHost } from "@/lib/host";

// Small in-memory TTL cache: the host->workspace map is tiny and rarely changes.
const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { id: number | null; at: number }>();

async function resolveWorkspaceId(origin: string, subdomain: string): Promise<number | null> {
  const host = `${subdomain}.${"owt.craazzzyyfoxx.me"}`;
  const cached = cache.get(host);
  const now = Date.now();
  if (cached && now - cached.at < CACHE_TTL_MS) return cached.id;
  try {
    const res = await fetch(`${origin}/api/v1/workspaces/by-host?host=${encodeURIComponent(host)}`, {
      headers: { accept: "application/json" },
    });
    const data = res.ok ? await res.json() : null;
    const id = data?.workspace_id ?? null;
    cache.set(host, { id, at: now });
    return id;
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const resolution = resolveHost(host);

  if (resolution.mode === "platform") {
    return NextResponse.next();
  }

  const workspaceId = await resolveWorkspaceId(request.nextUrl.origin, resolution.subdomain);
  if (workspaceId === null) {
    return NextResponse.rewrite(new URL("/not-configured", request.url), { status: 404 });
  }

  const headers = new Headers(request.headers);
  headers.set("x-owt-workspace-id", String(workspaceId));
  headers.set("x-owt-host-mode", "tenant");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  // Skip static assets + Next internals; run on pages + API-relative routes.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|webp|svg|ico)).*)"],
};
```

- [ ] **Step 3: Create the 404 "not configured" page**

```tsx
// frontend/src/app/(site)/not-configured/page.tsx
export default function NotConfigured() {
  return (
    <div className="mx-auto max-w-md py-24 text-center">
      <h1 className="text-2xl font-semibold">Workspace not configured</h1>
      <p className="mt-2 text-muted-foreground">
        This address is not linked to a workspace yet.
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Verify build + manual smoke**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.
Manual (after Task 17 env + a seeded subdomain): `curl -H "x-forwarded-host: team-a.owt.craazzzyyfoxx.me" http://localhost:3000/` returns the workspace-scoped page; an unknown subdomain returns the not-configured page.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/workspace.service.ts frontend/src/middleware.ts "frontend/src/app/(site)/not-configured/page.tsx"
git commit -m "feat(host): resolve host->workspace in middleware"
```

---

### Task 7: Scope precedence (header beats cookie)

**Files:**
- Modify: `frontend/src/lib/api-fetch.ts` (`getServerWorkspaceId`, ~lines 77-85)

**Interfaces:**
- Consumes: `x-owt-workspace-id` header (Task 6).
- Produces: server-side workspace scope preferring the host header over the cookie.

- [ ] **Step 1: Modify `getServerWorkspaceId`**

Replace the body so the host header wins over the cookie (white-label lock):

```typescript
const getServerWorkspaceId = cache(async (): Promise<string | undefined> => {
  try {
    const { headers, cookies } = await import("next/headers");
    const headerId = (await headers()).get("x-owt-workspace-id");
    if (headerId) return headerId;
    const cookieStore = await cookies();
    return cookieStore.get("owt-workspace-id")?.value ?? cookieStore.get("aqt-workspace-id")?.value;
  } catch {
    return undefined;
  }
});
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api-fetch.ts
git commit -m "feat(scope): prefer host workspace header over cookie (white-label lock)"
```

---

### Task 8: Cookie rename (owt_*) with aqt_* read compat

**Files:**
- Modify: `gateway/internal/auth/auth.go` (`CookieName`, `extractToken`)
- Test: `gateway/internal/auth/auth_cookie_test.go` (new)
- Modify: `frontend/src/lib/auth-tokens.ts` (read `owt_* ?? aqt_*`, write `owt_*`)
- Modify: `frontend/src/lib/api-fetch.ts` (`owt-workspace-id` already handled in Task 7)
- Modify: `frontend/src/stores/workspace.store.ts` (write `owt-workspace-id`, read both)

**Interfaces:**
- Produces: canonical cookie names `owt_access_token`, `owt_refresh_token`, `owt-workspace-id`; reads fall back to `aqt_*`.

- [ ] **Step 1: Write the failing Go test**

```go
// gateway/internal/auth/auth_cookie_test.go
package auth

import (
	"net/http"
	"testing"
)

func TestExtractTokenPrefersOwtThenAqtCookie(t *testing.T) {
	cases := []struct {
		name    string
		cookies []*http.Cookie
		want    string
	}{
		{"owt only", []*http.Cookie{{Name: "owt_access_token", Value: "N"}}, "N"},
		{"aqt fallback", []*http.Cookie{{Name: "aqt_access_token", Value: "O"}}, "O"},
		{"owt wins", []*http.Cookie{{Name: "aqt_access_token", Value: "O"}, {Name: "owt_access_token", Value: "N"}}, "N"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r, _ := http.NewRequest("GET", "/", nil)
			for _, ck := range c.cookies {
				r.AddCookie(ck)
			}
			if got := extractToken(r); got != c.want {
				t.Fatalf("got %q want %q", got, c.want)
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && go test ./internal/auth/ -run TestExtractTokenPrefers -v`
Expected: FAIL (aqt fallback + owt name not handled).

- [ ] **Step 3: Update `auth.go`**

```go
// CookieName is the canonical access-token cookie; LegacyCookieName is read as a
// fallback during the aqt->owt rename so existing sessions are not logged out.
const CookieName = "owt_access_token"
const LegacyCookieName = "aqt_access_token"
```

In `extractToken`, replace the single cookie read with:

```go
	for _, name := range []string{CookieName, LegacyCookieName} {
		if c, err := r.Cookie(name); err == nil && c.Value != "" {
			return strings.TrimSpace(strings.TrimPrefix(c.Value, "Bearer "))
		}
	}
	return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && go test ./internal/auth/ -run TestExtractTokenPrefers -v`
Expected: PASS

- [ ] **Step 5: Update the frontend cookie sites**

In `frontend/src/lib/auth-tokens.ts`: read `Cookies.get("owt_access_token") ?? Cookies.get("aqt_access_token")`; write only `owt_access_token`. In `frontend/src/stores/workspace.store.ts`: write `owt-workspace-id`; read `owt-workspace-id ?? aqt-workspace-id`. (The `WORKSPACE_COOKIE` constant becomes `"owt-workspace-id"`, plus a `LEGACY_WORKSPACE_COOKIE = "aqt-workspace-id"` used only in reads.)

- [ ] **Step 6: Commit**

```bash
cd gateway && gofmt -w internal/auth/auth.go internal/auth/auth_cookie_test.go
git add gateway/internal/auth/ frontend/src/lib/auth-tokens.ts frontend/src/stores/workspace.store.ts
git commit -m "feat(auth): rename cookies to owt_* with aqt_* read fallback"
```

---

### Task 9: Signed OAuth state carries origin/redirect/action

**Files:**
- Modify: `backend/identity-service/src/services/oauth_service.py` (state encode/verify ~460-513, `generate_oauth_url` :513)
- Modify: `backend/identity-service/src/services/oauth_flows.py` (`get_url` :27, `callback` :37 — thread through + echo decoded fields)
- Modify: `backend/identity-service/src/core/config.py:77` (`OAUTH_REDIRECT` semantics: fixed apex callback)
- Test: `backend/identity-service/tests/test_oauth_state.py` (new; check for an existing tests dir first)

**Interfaces:**
- Produces: state payload `{origin, redirect, action, provider, nonce, exp}`, HMAC-signed; `generate_oauth_url(provider, *, origin, redirect, action)`; `verify_state(state) -> StatePayload` (raises on bad HMAC / expired / replayed nonce); `oauth_callback` RPC response gains `origin`, `redirect`, `action`.

- [ ] **Step 1: Write the failing test**

```python
# backend/identity-service/tests/test_oauth_state.py
import pytest

from src.services.oauth_service import OAuthService  # adjust import to the state fns


def test_state_roundtrip_carries_origin_and_action():
    svc = OAuthService  # or the module-level encode/verify helpers
    state = svc.encode_state(origin="https://team-a.owt.craazzzyyfoxx.me", redirect="/account", action="login", provider="discord")
    payload = svc.verify_state(state)
    assert payload.origin == "https://team-a.owt.craazzzyyfoxx.me"
    assert payload.redirect == "/account"
    assert payload.action == "login"
    assert payload.provider == "discord"


def test_state_rejects_tamper():
    svc = OAuthService
    state = svc.encode_state(origin="https://team-a.owt.craazzzyyfoxx.me", redirect="/", action="login", provider="discord")
    with pytest.raises(ValueError):
        svc.verify_state(state[:-2] + ("aa" if not state.endswith("aa") else "bb"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/identity-service && uv run pytest tests/test_oauth_state.py -q`
Expected: FAIL — `encode_state`/`verify_state` don't take these fields.

- [ ] **Step 3: Implement the state payload**

Extend the existing HMAC state helpers (`oauth_service.py:464-500`) to serialize a payload dict `{"o": origin, "r": redirect, "a": action, "p": provider, "n": nonce, "e": exp}` as `base64url(json).base64url(hmac_sha256(json, JWT_SECRET_KEY))`. `verify_state` splits, recomputes the HMAC (constant-time compare), checks `exp` (reject expired), and consumes `nonce` in Redis (single-use; reject on replay). Return a small dataclass `StatePayload(origin, redirect, action, provider)`.

In `generate_oauth_url` (:513) accept `origin`, `redirect`, `action` and pass them to `encode_state`. Keep `redirect_uri = settings.OAUTH_REDIRECT` (now the fixed apex callback for authorize + exchange, unchanged mechanically — `oauth_service.py:68/167/281`).

- [ ] **Step 4: Thread through flows + callback response**

In `oauth_flows.get_url` (:27) accept `origin`/`redirect`/`action` from the request payload and forward. In `oauth_flows.callback` (:37) call `verify_state`, and include `origin`/`redirect`/`action` in the returned envelope alongside the token.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend/identity-service && uv run pytest tests/test_oauth_state.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd backend && uv run ruff check identity-service/src/services/oauth_service.py identity-service/src/services/oauth_flows.py
git add backend/identity-service/
git commit -m "feat(oauth): carry origin/redirect/action in signed state"
```

---

### Task 10: Frontend OAuth start passes origin/redirect/action

**Files:**
- Modify: `frontend/src/lib/oauth-login.ts`
- Modify: `frontend/src/services/auth.service.ts` (`getOAuthUrl` signature)

**Interfaces:**
- Consumes: `generate_oauth_url(origin, redirect, action)` (Task 9).
- Produces: provider redirect with signed state; no `aqt_oauth_*` transient cookies.

- [ ] **Step 1: Extend the auth service**

In `frontend/src/services/auth.service.ts`, change `getOAuthUrl` to accept and forward params:

```typescript
  async getOAuthUrl(
    provider: OAuthProviderName,
    params: { origin: string; redirect: string; action: "login" | "link" },
  ): Promise<{ url: string; state: string }> {
    const res = await apiFetch(`/api/auth/oauth/${provider}/url`, {
      query: { origin: params.origin, redirect: params.redirect, action: params.action },
      skipWorkspace: true,
    });
    return res.json();
  }
```

- [ ] **Step 2: Rewrite `startOAuthLogin`**

Replace `frontend/src/lib/oauth-login.ts` body so the current host is the origin and no transient cookies are set:

```typescript
import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import type { OAuthProviderName } from "@/types/auth.types";

export async function startOAuthLogin(request: Request, provider: OAuthProviderName): Promise<NextResponse> {
  const { searchParams, origin } = new URL(request.url);
  const nextParam = searchParams.get("next");
  const action = searchParams.get("action") === "link" ? "link" : "login";

  let redirect = action === "link" ? "/account" : "/";
  if (nextParam) {
    try {
      const nextUrl = new URL(nextParam, origin);
      if (nextUrl.origin === origin) redirect = nextUrl.pathname + nextUrl.search;
    } catch {
      if (nextParam.startsWith("/")) redirect = nextParam;
    }
  }

  const { url } = await authService.getOAuthUrl(provider, { origin, redirect, action });
  return NextResponse.redirect(url);
}
```

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/oauth-login.ts frontend/src/services/auth.service.ts
git commit -m "feat(oauth): pass origin/redirect/action into signed state on start"
```

---

### Task 11: Frontend OAuth callback sets domain cookies + redirects to origin

**Files:**
- Modify: `frontend/src/lib/oauth-callback.ts`
- Modify: `frontend/src/services/auth.service.ts` (`exchangeOAuthCode` return type gains `origin`/`redirect`/`action`)

**Interfaces:**
- Consumes: callback envelope `{token, origin, redirect, action}` (Task 9); `Domain=.owt.craazzzyyfoxx.me`.
- Produces: session cookies valid across all subdomains; redirect to `origin + redirect`.

- [ ] **Step 1: Define the cookie domain + origin allow-list helper**

Add to `oauth-callback.ts`:

```typescript
import { resolveHost, PLATFORM_ZONE } from "@/lib/host";

const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

// Only redirect back to the platform apex or a valid tenant subdomain.
function isAllowedOrigin(origin: string): boolean {
  try {
    const u = new URL(origin);
    if (u.hostname === PLATFORM_ZONE) return true;
    return resolveHost(u.hostname).mode === "tenant";
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: Rewrite the callback to use state fields + domain cookies**

Replace the cookie-cross-check + redirect logic. Key changes: drop `expectedState`/`aqt_oauth_state`; get `origin`/`redirect`/`action` from the exchange response; set cookies with `domain: COOKIE_DOMAIN`; redirect to the origin host. Core of the success path:

```typescript
    const result = await authService.exchangeOAuthCode(provider, code, state, forwardedHeaders);
    const origin = isAllowedOrigin(result.origin) ? result.origin : `https://${PLATFORM_ZONE}`;
    const target = new URL(result.redirect || "/", origin);

    const response = NextResponse.redirect(target);
    response.cookies.set("owt_access_token", result.access_token, {
      httpOnly: false, sameSite: "lax", secure: process.env.NODE_ENV === "production",
      path: "/", domain: COOKIE_DOMAIN,
      maxAge: getTokenMaxAgeSeconds(result.access_token, FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS),
    });
    response.cookies.set("owt_refresh_token", result.refresh_token, {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
      path: "/", domain: COOKIE_DOMAIN, maxAge: 30 * 24 * 60 * 60,
    });
    return response;
```

For `action === "link"`, read the access token via `owt_access_token ?? aqt_access_token` (readable on the apex because it is now a domain cookie), then `authService.linkOAuth(...)` and redirect to `new URL("/account", origin)`.

- [ ] **Step 3: Update `exchangeOAuthCode` return type**

In `auth.service.ts`, type the response as `{ access_token: string; refresh_token: string; origin: string; redirect: string; action: "login" | "link" }`.

- [ ] **Step 4: Verify typecheck + manual**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.
Manual (after Task 17): log in on `team-a.owt.craazzzyyfoxx.me`; confirm the callback lands back on `team-a...` and the session is present on a second subdomain.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/oauth-callback.ts frontend/src/services/auth.service.ts
git commit -m "feat(oauth): domain cookies + origin redirect on callback"
```

---

### Task 12: Per-host, per-workspace SEO metadata

**Files:**
- Create: `frontend/src/lib/site-metadata.ts` (host origin + workspace metadata resolver)
- Modify: `frontend/src/app/layout.tsx` (static `metadata` → async `generateMetadata`)
- Modify: section layouts with hardcoded `metadataBase` — `frontend/src/app/(site)/{owal,statistics,encounters,matches,teams,tournaments,tournaments/analytics}/layout.tsx`

**Interfaces:**
- Consumes: `x-owt-workspace-id` / `x-forwarded-host` headers; `workspaceService.getById`; `Workspace.{seo_title,seo_description,icon_url}`.
- Produces: `resolveSiteMetadata(): Promise<{ name: string; description: string; origin: string; icon: string }>`.

- [ ] **Step 1: Implement the resolver**

```typescript
// frontend/src/lib/site-metadata.ts
import { headers } from "next/headers";
import workspaceService from "@/services/workspace.service";
import { SITE_NAME } from "@/config/site";

export async function resolveSiteMetadata() {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "owt.craazzzyyfoxx.me";
  const proto = h.get("x-forwarded-proto") ?? "https";
  const origin = `${proto}://${host.split(",")[0].trim()}`;

  const wsId = h.get("x-owt-workspace-id");
  if (!wsId) {
    return { name: SITE_NAME, description: `${SITE_NAME} — Overwatch tournament results & stats.`, origin, icon: "/favicon.ico" };
  }
  try {
    const ws = await workspaceService.getById(Number(wsId));
    return {
      name: ws.seo_title ?? ws.name,
      description: ws.seo_description ?? ws.description ?? `${ws.name} — tournaments`,
      origin,
      icon: ws.icon_url ?? "/favicon.ico",
    };
  } catch {
    return { name: SITE_NAME, description: `${SITE_NAME}`, origin, icon: "/favicon.ico" };
  }
}
```

- [ ] **Step 2: Convert the root layout**

In `frontend/src/app/layout.tsx`, replace the static `export const metadata` with:

```typescript
import type { Metadata } from "next";
import { resolveSiteMetadata } from "@/lib/site-metadata";

export async function generateMetadata(): Promise<Metadata> {
  const { name, description, origin, icon } = await resolveSiteMetadata();
  return {
    title: name,
    description,
    metadataBase: new URL(origin),
    icons: { icon },
    openGraph: { title: name, description, url: origin, type: "website", siteName: name, locale: "en_US" },
  };
}
```

- [ ] **Step 3: Convert section layouts**

For each section layout that hardcodes `metadataBase: new URL("https://aqt.craazzzyyfoxx.me")`, replace the static `metadata` with an async `generateMetadata` that calls `resolveSiteMetadata()` and sets `metadataBase: new URL(origin)` + `openGraph.siteName: name` (keep each section's own title/description text but base the URL/siteName on the resolver).

- [ ] **Step 4: Verify typecheck + manual**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.
Manual: view-source on `team-a.owt.craazzzyyfoxx.me` shows `<title>` + OG `site_name` = the workspace's `seo_title`, canonical host = that subdomain.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/site-metadata.ts frontend/src/app/layout.tsx "frontend/src/app/(site)/"
git commit -m "feat(seo): per-host per-workspace metadata"
```

---

### Task 13: Host-scoped sitemap + robots

**Files:**
- Modify: `frontend/src/app/sitemap.ts`
- Modify: `frontend/src/app/robots.ts`

**Interfaces:**
- Consumes: `resolveSiteMetadata` (Task 12).

- [ ] **Step 1: Base both on the resolved origin**

In `sitemap.ts` and `robots.ts`, replace `SITE_URL_OBJ` with the per-request `origin` from `resolveSiteMetadata()` (both files are already dynamic route handlers, so `headers()` is available). `robots.ts` `host` + `sitemap` fields use `origin`.

- [ ] **Step 2: Verify + commit**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.

```bash
git add frontend/src/app/sitemap.ts frontend/src/app/robots.ts
git commit -m "feat(seo): host-scoped sitemap and robots"
```

---

### Task 14: White-label UI gating (hide switcher + communities)

**Files:**
- Modify: `frontend/src/app/(site)/layout.tsx` (read `x-owt-host-mode`, pass `tenantMode` down)
- Modify: `frontend/src/components/Header.tsx` (hide `WorkspaceSwitcher` in tenant mode)
- Modify: `frontend/src/app/(site)/(home)/page.tsx` (hide communities list in tenant mode)

**Interfaces:**
- Consumes: `x-owt-host-mode` header (Task 6).

- [ ] **Step 1: Surface tenant mode from the server layout**

In `frontend/src/app/(site)/layout.tsx` read `const tenantMode = (await headers()).get("x-owt-host-mode") === "tenant";` and pass it to `<Header tenantMode={tenantMode} />`. (The layout is already async — it fetches branding.)

- [ ] **Step 2: Gate the switcher**

In `Header.tsx`, accept `tenantMode?: boolean` and render `WorkspaceSwitcher` only when `!tenantMode`.

- [ ] **Step 3: Gate the communities section**

In the home page, when tenant mode is active (read the header there too, or accept a prop), hide `CommunitiesSection` / "all communities" cards.

- [ ] **Step 4: Verify + commit**

Run: `cd frontend && bunx tsc --noEmit -p tsconfig.json 2>&1 | grep -v "^\.next/" | grep "error TS"` → expect empty.

```bash
git add "frontend/src/app/(site)/layout.tsx" frontend/src/components/Header.tsx "frontend/src/app/(site)/(home)/page.tsx"
git commit -m "feat(white-label): hide switcher + communities on tenant hosts"
```

---

### Task 15: Admin editor — subdomain + SEO fields

**Files:**
- Modify: `frontend/src/app/admin/workspaces/page.tsx` (extend the edit dialog + form types + service payload)
- Modify: `frontend/src/services/workspace.service.ts` (`update` payload type)

**Interfaces:**
- Consumes: `WorkspaceUpdate` fields (Task 3).

- [ ] **Step 1: Extend the update payload type**

In `workspace.service.ts` `update(...)`, add `subdomain?: string | null; seo_title?: string | null; seo_description?: string | null;`.

- [ ] **Step 2: Extend the admin edit form**

In `admin/workspaces/page.tsx`, add to `WorkspaceUpdateFormData`: `subdomain?`, `seo_title?`, `seo_description?`. Populate them in `handleEdit` from `ws`. Add a "Domain & SEO" section to the edit dialog (mirror the branding section): a text input for `subdomain` (with helper text `{value}.owt.craazzzyyfoxx.me` and client-side `^[a-z0-9-]*$` filtering), and text inputs for `seo_title` / `seo_description`. Save via the existing `workspaceService.update`.

- [ ] **Step 3: Verify + commit**

Run: `cd frontend && bunx eslint src/app/admin/workspaces/page.tsx src/services/workspace.service.ts` → 0 errors; `bunx tsc --noEmit ...` clean.

```bash
git add frontend/src/app/admin/workspaces/page.tsx frontend/src/services/workspace.service.ts
git commit -m "feat(admin): edit workspace subdomain + seo"
```

---

### Task 16: Gateway WS origin allows `*.owt.craazzzyyfoxx.me`

**Files:**
- Modify: `gateway/internal/ws/handler.go:47-58` (origin patterns)
- Modify: `gateway/internal/config/config.go:130` (parse a default including the wildcard)
- Test: `gateway/internal/ws/origin_test.go` (if the pattern check is extractable) or config test

**Interfaces:**
- Produces: WS accepts origins matching `*.owt.craazzzyyfoxx.me` + the apex, never `InsecureSkipVerify`.

- [ ] **Step 1: Add the wildcard to the allowed origin patterns**

Ensure `GATEWAY_WS_ALLOWED_ORIGINS` (config default + prod env) includes `owt.craazzzyyfoxx.me` and `*.owt.craazzzyyfoxx.me`. `coder/websocket` `OriginPatterns` supports `*` glob, so `accept.OriginPatterns` already matches subdomains once the pattern is present. Remove any `InsecureSkipVerify` fallback path (fail closed).

- [ ] **Step 2: Verify + commit**

Run: `cd gateway && go build ./... && go test ./internal/ws/ ./internal/config/`

```bash
git add gateway/internal/ws/handler.go gateway/internal/config/config.go
git commit -m "feat(ws): allow *.owt.craazzzyyfoxx.me origins"
```

---

### Task 17: Config, env, and ops runbook

**Files:**
- Modify: `frontend/.env.example`, `docker-compose.production.yml` (`NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SITE_NAME`)
- Modify: `backend/env/auth.env.example` (`OAUTH_REDIRECT`)
- Modify: `backend/env/common.env.example` (`GATEWAY_WS_ALLOWED_ORIGINS`)
- Create: `docs/superpowers/plans/2026-07-06-subdomains-ops-runbook.md`

**Interfaces:** none (config/docs).

- [ ] **Step 1: Set canonical values**

- `NEXT_PUBLIC_SITE_URL = https://owt.craazzzyyfoxx.me`
- `OAUTH_REDIRECT = https://owt.craazzzyyfoxx.me/auth/callback`
- `GATEWAY_WS_ALLOWED_ORIGINS = https://owt.craazzzyyfoxx.me,https://*.owt.craazzzyyfoxx.me`

- [ ] **Step 2: Write the ops runbook** (external, cannot be done from the repo)

Document, with exact records:
1. **DNS:** wildcard `*.owt.craazzzyyfoxx.me` → the ingress IP (A/CNAME).
2. **TLS (Traefik, external):** wildcard cert for `*.owt.craazzzyyfoxx.me` via DNS-01 ACME (avoids Let's Encrypt per-domain rate limits). Note the DNS provider credential requirement.
3. **OAuth provider consoles:** register `https://owt.craazzzyyfoxx.me/auth/callback` as the (only) redirect URI for Discord, Twitch, Battle.net.

- [ ] **Step 3: Commit**

```bash
git add frontend/.env.example docker-compose.production.yml backend/env/auth.env.example backend/env/common.env.example docs/superpowers/plans/2026-07-06-subdomains-ops-runbook.md
git commit -m "chore(subdomains): canonical env + ops runbook"
```

---

## Self-Review

**Spec coverage (Phase 1 rows of the spec):**
- Data model (subdomain + seo) → Tasks 2, 3. ✓
- Resolver (by_host + middleware + header precedence) → Tasks 4, 5, 6, 7. ✓
- White-label lock → Tasks 7 (scope) + 14 (UI). ✓
- OAuth single callback + signed state + domain cookies → Tasks 9, 10, 11. ✓
- Cookie rebrand (owt_* write, aqt_* read) → Task 8 (+ used in 11). ✓
- Per-host SEO + sitemap/robots → Tasks 12, 13. ✓
- WS origin `*.owt` → Task 16. ✓
- Admin editor → Task 15. ✓
- Ops (DNS/TLS/provider registration) → Task 17. ✓
- (Phase 2 — custom domains, SSO ticket, on-demand TLS, dynamic WS validation — intentionally excluded; separate plan.)

**Placeholder scan:** No TBD/TODO; integration-only steps (middleware, cookie-domain in a real browser) use explicit `curl`/manual verification because they aren't unit-testable — that is a deliberate verification method, not a placeholder.

**Type consistency:** `resolveHost`/`HostResolution` (Task 5) reused in Tasks 6, 11. `x-owt-workspace-id` / `x-owt-host-mode` headers set in Task 6, read in Tasks 7, 12, 14. State payload fields `{origin, redirect, action, provider}` produced in Task 9, consumed in Tasks 10, 11. Cookie names `owt_access_token`/`owt_refresh_token`/`owt-workspace-id` consistent across Tasks 8, 11.
