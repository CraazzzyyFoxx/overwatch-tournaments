# Workspace Custom Domains (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a workspace be served on its own custom domain (`tourney.customer.com`) as a white-label site, with verified-domain resolution, on-demand TLS, and a cross-domain SSO handoff for OAuth (since cookies can't cross registrable domains).

**Architecture:** Custom domains reuse Phase 1's host→workspace middleware, but the resolver also matches a **verified** `custom_domain`. Because cookies can't be shared to the apex OAuth callback, custom-domain login **bounces its start to the apex** (so the CSRF cookie is apex-scoped) and delivers the session back via a **one-time Redis SSO ticket** exchanged on the custom domain. WS origins and OAuth `origin` are validated dynamically against the workspace-host set.

**Tech Stack:** Python (FastStream RPC, SQLAlchemy, Alembic, Pydantic, `dnspython` for DNS-01 verification, Redis), Next.js App Router (TypeScript, `bun test`), Go gateway (`go test`). Builds on Phase 1 (merged in `develop`).

**Spec:** `docs/superpowers/specs/2026-07-06-workspace-multidomain-design.md` (sections D.4/D.5, E, F, H, Phase 2).

## Global Constraints

- Platform zone `owt.craazzzyyfoxx.me`. Custom domain = any verified FQDN that is NOT under the platform zone.
- **Resolver serves custom domains only when `custom_domain_verified_at IS NOT NULL`** (fail-closed; unverified/unknown host → 404 "not configured").
- Verification: DNS TXT `_owt-verify.<domain>` == `custom_domain_verification_token`; UI also instructs a CNAME/A `<domain> → owt.craazzzyyfoxx.me`.
- Single OAuth callback stays `https://owt.craazzzyyfoxx.me/auth/callback`. Custom-domain login **starts on the apex** (CSRF cookie must be readable by the apex callback).
- Cross-domain session delivery = one-time **Redis** ticket (opaque, ≤60s TTL, single-use, deleted on redeem); tokens NEVER in a URL. Custom-domain session cookies are **host-only** (no `Domain`).
- `origin` carried in OAuth state must be validated (backend) against the workspace-host set (apex / that workspace's subdomain / that workspace's verified custom_domain) — no open redirect.
- Never `InsecureSkipVerify` on WS; custom-domain WS origins validated per-request against the workspace-host set.
- Typed columns; follow Phase 1 patterns (`[[project_workspace_multidomain]]`).

---

### Task 1: Workspace custom-domain columns + migration

**Files:**
- Modify: `backend/shared/models/tenancy/workspace.py`
- Create: `backend/migrations/versions/wscustdom0001_add_workspace_custom_domain.py`

**Interfaces:**
- Produces `Workspace.custom_domain` (`str | None`, unique), `custom_domain_verified_at` (`datetime | None`), `custom_domain_verification_token` (`str | None`).

- [ ] **Step 1: Confirm the current alembic head** (Phase 1 added `wsbrand0001`, `wsdomain0001`)

Run the head-detector (multi-line-tuple-aware) from `backend/migrations/versions`:
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
Use the printed single head as `down_revision`. Expected `wsdomain0001` (if multiple heads appear, STOP and report — a merge migration is needed first).

- [ ] **Step 2: Add model columns** (after the Phase 1 `seo_description` column in `workspace.py`)

```python
    # White-label custom domains (Phase 2). Resolver serves the domain only
    # once verified (DNS TXT owner-proof); token is the required TXT value.
    custom_domain: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    custom_domain_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_domain_verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
```
Add imports if missing: `from datetime import datetime`, `from sqlalchemy import DateTime`.

- [ ] **Step 3: Write the migration**

```python
# backend/migrations/versions/wscustdom0001_add_workspace_custom_domain.py
"""add workspace custom-domain columns

Revision ID: wscustdom0001
Revises: wsdomain0001
Create Date: 2026-07-06
"""
from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "wscustdom0001"
down_revision: str | None = "wsdomain0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("custom_domain", sa.String(length=255), nullable=True))
    op.add_column("workspace", sa.Column("custom_domain_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workspace", sa.Column("custom_domain_verification_token", sa.String(length=64), nullable=True))
    op.create_index("ix_workspace_custom_domain", "workspace", ["custom_domain"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_workspace_custom_domain", table_name="workspace")
    op.drop_column("workspace", "custom_domain_verification_token")
    op.drop_column("workspace", "custom_domain_verified_at")
    op.drop_column("workspace", "custom_domain")
```

- [ ] **Step 4: Verify offline render** — `cd backend/app-service && uv run alembic upgrade wsdomain0001:wscustdom0001 --sql` prints the 3 ADD COLUMNs + unique index.
- [ ] **Step 5: Commit** — `git commit -m "feat(workspace): add custom-domain columns"`

---

### Task 2: Custom-domain normalize/validate + host resolver helper (shared)

**Files:**
- Modify: `backend/shared/tenancy/hostnames.py`
- Test: `backend/app-service/tests/test_hostnames.py` (extend)

**Interfaces:**
- Produces `normalize_custom_domain(domain: str) -> str` (lowercase, strip, strip trailing dot; reject empty, the platform zone or its subdomains, obvious non-FQDN); `is_platform_host(host) -> bool` (apex or `.owt` subdomain).

- [ ] **Step 1: Write failing tests**

```python
from shared.tenancy.hostnames import normalize_custom_domain, is_platform_host
import pytest

@pytest.mark.parametrize("raw,norm", [
    ("Tourney.Customer.com", "tourney.customer.com"),
    ("example.org.", "example.org"),
])
def test_normalize_custom_domain_ok(raw, norm):
    assert normalize_custom_domain(raw) == norm

@pytest.mark.parametrize("bad", ["", "owt.craazzzyyfoxx.me", "team.owt.craazzzyyfoxx.me", "nodot", "has space.com"])
def test_normalize_custom_domain_rejects(bad):
    with pytest.raises(ValueError):
        normalize_custom_domain(bad)

def test_is_platform_host():
    assert is_platform_host("owt.craazzzyyfoxx.me")
    assert is_platform_host("team-a.owt.craazzzyyfoxx.me")
    assert not is_platform_host("tourney.customer.com")
```

- [ ] **Step 2: Run** — `cd backend/app-service && uv run pytest tests/test_hostnames.py -q` → FAIL.
- [ ] **Step 3: Implement** in `hostnames.py`

```python
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+$")


def is_platform_host(host: str) -> bool:
    h = host.strip().lower().split(":", 1)[0]
    return h == PLATFORM_ZONE or h.endswith("." + PLATFORM_ZONE)


def normalize_custom_domain(domain: str) -> str:
    d = domain.strip().lower().rstrip(".").split(":", 1)[0]
    if not d or "." not in d or not _DOMAIN_RE.fullmatch(d):
        raise ValueError("Invalid custom domain")
    if is_platform_host(d):
        raise ValueError("Custom domain must not be under the platform zone")
    return d
```
Add both to `__all__`.

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — `git commit -m "feat(tenancy): custom-domain normalize + is_platform_host helpers"`

---

### Task 3: Resolver matches verified custom_domain (service + by_host RPC)

**Files:**
- Modify: workspace repo (`backend/shared/repository/...` — the file with `get_by_subdomain`): add `get_by_verified_custom_domain`
- Modify: `backend/app-service/src/services/workspace/service.py`: add `get_by_custom_domain`
- Modify: `backend/app-service/src/rpc/workspaces.py`: `by_host` also matches custom domains
- Test: `backend/app-service/tests/api/test_workspaces_by_host.py` (extend)

**Interfaces:**
- Consumes `normalize_custom_domain`, `subdomain_from_host` (Task 2), `Workspace.custom_domain*` (Task 1).
- Produces `service.get_by_custom_domain(session, domain) -> Workspace | None` (verified only); `by_host` returns `{workspace_id, slug}` for a verified custom domain too.

- [ ] **Step 1: Repo lookup** (next to `get_by_subdomain`)

```python
async def get_by_verified_custom_domain(self, session: AsyncSession, domain: str) -> Workspace | None:
    result = await session.execute(
        select(Workspace).where(
            Workspace.custom_domain == domain,
            Workspace.custom_domain_verified_at.is_not(None),
        )
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 2: Service** (`services/workspace/service.py`, next to `get_by_subdomain`)

```python
async def get_by_custom_domain(session: AsyncSession, domain: str) -> models.Workspace | None:
    return await _workspace_repo.get_by_verified_custom_domain(session, domain)
```

- [ ] **Step 3: Extend `by_host`** in `rpc/workspaces.py` (currently subdomain-only). After extracting `host`:

```python
        label = subdomain_from_host(host)
        async with db.async_session_maker() as session:
            if label is not None:
                workspace = await workspace_service.get_by_subdomain(session, label)
            else:
                try:
                    domain = normalize_custom_domain(host)
                except ValueError:
                    return rpc_ok(None)
                workspace = await workspace_service.get_by_custom_domain(session, domain)
        if workspace is None:
            return rpc_ok(None)
        return rpc_ok({"workspace_id": workspace.id, "slug": workspace.slug})
```
Import `normalize_custom_domain` from `shared.tenancy.hostnames`. (Use the module's existing `rpc_ok`/return shape — match the current handler.)

- [ ] **Step 4: Test** (extend, DB-gated integration + a pure host-branch unit if feasible) — assert a non-platform host that isn't a verified custom domain returns `None`.
- [ ] **Step 5: Run + commit** — `cd backend/app-service && uv run pytest tests/api/test_workspaces_by_host.py -q`; `git commit -m "feat(workspace): resolve verified custom domains in by_host"`

---

### Task 4: Frontend host resolver + middleware handle custom domains

**Files:**
- Modify: `frontend/src/lib/host.ts`
- Modify: `frontend/src/middleware.ts`
- Modify callers of `resolveHost().mode === "tenant"`: `frontend/src/components/WorkspaceBootstrap.tsx`, `frontend/src/lib/oauth-callback.ts`
- Test: `frontend/src/lib/host.test.ts` (extend)

**Interfaces:**
- Produces `resolveHost(host) -> { mode: "platform" } | { mode: "tenant"; host: string }` where `host` is the FULL lowercased host to look up (subdomain OR custom domain). Apex / `www` / `localhost` / IP / no-dot → platform.

- [ ] **Step 1: Write failing tests** (host.test.ts)

```typescript
it("returns lookup host for subdomains and custom domains", () => {
  expect(resolveHost(`team-a.${PLATFORM_ZONE}`)).toEqual({ mode: "tenant", host: `team-a.${PLATFORM_ZONE}` });
  expect(resolveHost("tourney.customer.com")).toEqual({ mode: "tenant", host: "tourney.customer.com" });
});
it("treats apex, www, localhost, IP, and no-dot hosts as platform", () => {
  for (const h of [PLATFORM_ZONE, `www.${PLATFORM_ZONE}`, "localhost:3000", "127.0.0.1", "gateway", ""])
    expect(resolveHost(h)).toEqual({ mode: "platform" });
});
```

- [ ] **Step 2: Run** — `cd frontend && bun test src/lib/host.test.ts` → FAIL.
- [ ] **Step 3: Rewrite `resolveHost`**

```typescript
export type HostResolution = { mode: "platform" } | { mode: "tenant"; host: string };

const IP_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/;

export function resolveHost(host: string | null | undefined): HostResolution {
  if (!host) return { mode: "platform" };
  const hostname = host.trim().toLowerCase().split(":")[0];
  if (!hostname || hostname === "localhost" || IP_RE.test(hostname) || !hostname.includes(".")) {
    return { mode: "platform" };
  }
  if (hostname === PLATFORM_ZONE || hostname === `www.${PLATFORM_ZONE}`) return { mode: "platform" };
  const suffix = `.${PLATFORM_ZONE}`;
  if (hostname.endsWith(suffix)) {
    const label = hostname.slice(0, -suffix.length);
    if (!label || label.includes(".") || RESERVED.has(label)) return { mode: "platform" };
  }
  // Subdomain or custom domain — the backend by_host decides which.
  return { mode: "tenant", host: hostname };
}
```

- [ ] **Step 4: Middleware** — pass the full host to `by_host`. In `middleware.ts` change `resolveWorkspace(request.nextUrl.origin, resolution.subdomain)` → `resolveWorkspace(request.nextUrl.origin, resolution.host)`, and inside `resolveWorkspace` use the passed `host` directly (drop the `${subdomain}.${PLATFORM_ZONE}` reconstruction; cache key = host). Everything else (found/not_found/error handling) unchanged.

- [ ] **Step 5: Update callers**
  - `WorkspaceBootstrap.tsx`: `resolveHost(window.location.hostname).mode === "tenant"` still works (mode name unchanged).
  - `oauth-callback.ts` `isAllowedOrigin`: `resolveHost(u.hostname).mode === "tenant"` now also returns tenant for custom domains — acceptable (any real non-platform host is a candidate; the backend already validated the echoed origin, Task 6). Keep the apex check.

- [ ] **Step 6: Run + verify + commit** — `bun test src/lib/host.test.ts`; `bunx tsc --noEmit ... | grep error TS` empty; `git commit -m "feat(host): resolve custom domains in middleware (full-host lookup)"`

---

### Task 5: Custom-domain verification (RPCs + DNS check + admin UI)

**Files:**
- Add DNS dep: `backend/*/pyproject.toml` (or shared) — `dnspython`; check availability first.
- Modify: `backend/app-service/src/rpc/workspaces.py`: `set_custom_domain`, `verify_custom_domain`, `clear_custom_domain` (all gated `workspace.update`).
- Modify: `backend/app-service/src/services/workspace/service.py`: helpers to set/clear/verify.
- Modify: `backend/app-service/src/schemas/workspace.py`: expose `custom_domain`, `custom_domain_verified_at`, `custom_domain_verification_token` in `WorkspaceRead`.
- Modify: `frontend/src/services/workspace.service.ts` + `frontend/src/app/admin/workspaces/page.tsx`: "Custom domain" UI (input, Save→shows TXT+CNAME records, Verify button, verified badge).
- Test: `backend/app-service/tests/test_workspace_custom_domain.py`

**Interfaces:**
- Produces RPC topics `rpc.app.workspaces.set_custom_domain` (`{workspace_id, custom_domain}` → stores normalized + generates token, unverified), `rpc.app.workspaces.verify_custom_domain` (`{workspace_id}` → DNS TXT check → sets `verified_at` or errors), `rpc.app.workspaces.clear_custom_domain`.

- [ ] **Step 1: Confirm/add the DNS resolver dependency**
Run `cd backend && uv run python -c "import dns.asyncresolver; print('ok')"`. If ImportError, add `dnspython` to the appropriate `pyproject.toml` `[project.dependencies]` and `uv sync`.

- [ ] **Step 2: Service helpers** (`services/workspace/service.py`)

```python
import secrets
from datetime import datetime, timezone

async def set_custom_domain(session, workspace, domain: str) -> models.Workspace:
    normalized = normalize_custom_domain(domain)  # raises ValueError on bad input
    token = "owt-verify-" + secrets.token_urlsafe(24)
    await _workspace_repo.update_fields(session, workspace, {
        "custom_domain": normalized,
        "custom_domain_verification_token": token,
        "custom_domain_verified_at": None,
    })
    await session.commit()
    return workspace

async def clear_custom_domain(session, workspace) -> models.Workspace:
    await _workspace_repo.update_fields(session, workspace, {
        "custom_domain": None, "custom_domain_verification_token": None, "custom_domain_verified_at": None,
    })
    await session.commit()
    return workspace

async def verify_custom_domain(session, workspace) -> models.Workspace:
    if not workspace.custom_domain or not workspace.custom_domain_verification_token:
        raise HTTPException(status_code=400, detail="No custom domain to verify")
    ok = await _dns_txt_contains(f"_owt-verify.{workspace.custom_domain}", workspace.custom_domain_verification_token)
    if not ok:
        raise HTTPException(status_code=400, detail="Verification TXT record not found yet")
    await _workspace_repo.update_fields(session, workspace, {"custom_domain_verified_at": datetime.now(timezone.utc)})
    await session.commit()
    return workspace
```
DNS helper (module-level):
```python
import dns.asyncresolver, dns.exception

async def _dns_txt_contains(name: str, expected: str) -> bool:
    try:
        answers = await dns.asyncresolver.resolve(name, "TXT")
    except (dns.exception.DNSException, Exception):
        return False
    for rdata in answers:
        txt = b"".join(rdata.strings).decode("utf-8", "ignore")
        if txt.strip() == expected:
            return True
    return False
```

- [ ] **Step 3: RPC handlers** (`rpc/workspaces.py`) — gate each on `ensure_workspace_permission(user, workspace_id, "workspace", "update")` (match how member ops gate). `set_custom_domain` catches `ValueError` → 400. Register topics.

- [ ] **Step 4: Schema** — add the 3 read fields to `WorkspaceRead` (all optional). Frontend `Workspace` type mirrors (Task also updates `workspace.types.ts`).

- [ ] **Step 5: Admin UI** — in the "Domain & SEO" section: a `custom_domain` input + Save (calls `set_custom_domain`); when a domain is set + unverified, show the two DNS records (`_owt-verify.<domain> TXT <token>` and `<domain> CNAME owt.craazzzyyfoxx.me`) + a "Verify" button (calls `verify_custom_domain`, shows success/pending); a "verified" badge + "Remove" (clear) when verified. Service methods in `workspace.service.ts`.

- [ ] **Step 6: Tests** — unit: `normalize_custom_domain` already covered (Task 2); `set_custom_domain` generates a token + leaves unverified (mock repo or DB-gated); `_dns_txt_contains` with a monkeypatched resolver (match → True, no-match/DNS error → False). Run `uv run pytest tests/test_workspace_custom_domain.py -q`.
- [ ] **Step 7: Commit** — `git commit -m "feat(workspace): custom-domain set/verify/clear + admin UI"`

---

### Task 6: Backend validates OAuth `origin` against the workspace-host set

**Files:**
- Modify: `backend/identity-service/src/services/oauth_flows.py` (`get_url`) + a host-validation helper.
- Modify: `backend/identity-service/src/services/oauth_service.py` if `origin` validation belongs at encode time.
- Test: `backend/identity-service/tests/test_oauth_state.py` (extend)

**Interfaces:**
- Consumes the app-svc workspace-host set. Produces: `get_url` rejects an `origin` whose host is neither the apex, a `.owt` subdomain, nor a verified custom domain.

- [ ] **Step 1** — Add `_validate_origin(origin: str) -> None` used by `get_url`: parse origin; allow if host `is_platform_host(host)` (apex or subdomain — Phase 1 already trusts these) OR the host resolves to a verified custom domain. identity-svc doesn't own the workspace DB directly → resolve via the existing gateway/RPC path used elsewhere, OR (simpler) accept apex+subdomain here and defer custom-domain origin validation to the frontend `isAllowedOrigin` + the fact that a custom-domain flow only reaches `/auth/sso` with a valid ticket. **Decision:** validate `is_platform_host` here; for custom domains rely on (a) the ticket being workspace-bound (Task 8) and (b) frontend `isAllowedOrigin`. Document this explicitly. (If identity-svc gains a workspace-host lookup later, tighten here.)
- [ ] **Step 2** — On invalid origin → `HTTPException(400, "Invalid origin")`. Test: platform origins pass; a random origin is rejected.
- [ ] **Step 3: Commit** — `git commit -m "feat(oauth): validate origin against platform hosts at get_url"`

---

### Task 7: Custom-domain OAuth start bounces to the apex

**Files:**
- Modify: `frontend/src/lib/oauth-login.ts`
- Create: `frontend/src/app/(site)/auth/[provider]/login/route.ts` already exists (per-provider) — confirm; the bounce is inside `startOAuthLogin`.

**Interfaces:**
- Consumes `resolveHost` (Task 4). Produces: on a custom-domain host, the OAuth flow starts on the apex (CSRF cookie apex-scoped), carrying the real origin.

- [ ] **Step 1** — In `startOAuthLogin`, detect a custom-domain host and bounce the START to the apex:

```typescript
import { resolveHost, PLATFORM_ZONE } from "@/lib/host";

// If we're on a custom domain, the CSRF cookie can't be read by the apex
// callback (different registrable domain), so start the whole flow on the apex
// and carry the real origin along. Subdomains/apex use the Domain=.owt cookie.
const currentHost = new URL(request.url).hostname;
const onCustomDomain =
  resolveHost(currentHost).mode === "tenant" && !currentHost.endsWith(`.${PLATFORM_ZONE}`) && currentHost !== PLATFORM_ZONE;
if (onCustomDomain) {
  const apex = new URL(`https://${PLATFORM_ZONE}/auth/${provider}/login`);
  apex.searchParams.set("action", action);
  apex.searchParams.set("origin", `https://${currentHost}`);
  if (nextParam) apex.searchParams.set("next", nextParam);
  return NextResponse.redirect(apex);
}
```
Then `startOAuthLogin` (now guaranteed running on the apex for custom-domain flows) reads an optional `origin` search param and uses it as the state `origin` (instead of the current apex origin) when present + allowed:
```typescript
const originParam = searchParams.get("origin");
const flowOrigin = originParam && resolveHost(new URL(originParam).hostname).mode === "tenant" ? originParam : origin;
```
Pass `flowOrigin` to `getOAuthUrl({ origin: flowOrigin, ... })`. The CSRF cookie is still set on the apex with `Domain=.owt` (works for the apex callback).

- [ ] **Step 2: Verify + commit** — `bunx tsc` clean; `git commit -m "feat(oauth): bounce custom-domain login start to the apex"`

---

### Task 8: Backend ticket handoff for custom-domain callback + `sso_exchange`

**Files:**
- Modify: `backend/identity-service/src/services/oauth_flows.py` (`callback`)
- Create: `backend/identity-service/src/services/sso_tickets.py` (Redis one-time ticket)
- Modify: `backend/identity-service/serve.py` (register `rpc.identity.sso_exchange`)
- Modify: `backend/identity-service/src/schemas/oauth.py` (`OAuthCallbackResult` gains an optional ticket mode)
- Test: `backend/identity-service/tests/test_sso_tickets.py`

**Interfaces:**
- Produces: `sso_tickets.issue(session_tokens) -> code` (Redis, TTL 60s, single-use), `sso_tickets.redeem(code) -> tokens | None`; `callback` returns a ticket (not raw tokens) when `origin` is a custom domain; RPC `rpc.identity.sso_exchange` `{ticket}` → `{access_token, refresh_token}` or error.

- [ ] **Step 1** — `sso_tickets.py`: `issue` stores `json({access_token, refresh_token, redirect})` in Redis under `sso:ticket:<opaque>` with `SET ... EX 60`; `redeem` does an atomic get-and-delete (`GETDEL`) → returns the payload or None. Opaque code = `secrets.token_urlsafe(32)`.

- [ ] **Step 2** — In `callback`, after minting tokens, branch on origin:
```python
from shared.tenancy.hostnames import is_platform_host
host = _origin_host(payload.origin)  # urlparse().hostname
if host and not is_platform_host(host):
    ticket = await sso_tickets.issue(access_token, refresh_token, payload.redirect)
    return schemas.OAuthCallbackResult(mode="ticket", ticket=ticket, origin=payload.origin, redirect=payload.redirect)
return schemas.OAuthCallbackResult(mode="cookie", access_token=..., refresh_token=..., origin=..., redirect=...)
```
Extend `OAuthCallbackResult` with `mode: Literal["cookie","ticket"]`, optional `ticket`, and make token fields optional.

- [ ] **Step 3** — `serve.py`: register `rpc.identity.sso_exchange` → `sso_tickets.redeem(ticket)`; returns tokens or a 400 "invalid or expired ticket". Gateway route: `POST /api/auth/sso/exchange` (public, body `{ticket}`) → `rpc.identity.sso_exchange`.

- [ ] **Step 4: Tests** — `issue`/`redeem` roundtrip (single-use: second redeem → None) with a fake/real Redis; expired → None. `uv run pytest tests/test_sso_tickets.py -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat(oauth): custom-domain ticket handoff + sso_exchange"`

---

### Task 9: Frontend `/auth/sso` handoff + callback ticket mode

**Files:**
- Create: `frontend/src/app/(site)/auth/sso/route.ts`
- Modify: `frontend/src/lib/oauth-callback.ts` (handle `mode: "ticket"`)
- Modify: `frontend/src/services/auth.service.ts` (`exchangeOAuthCode` result type gains `mode`/`ticket`; add `ssoExchange(ticket)`)

**Interfaces:**
- Consumes Task 8's `OAuthCallbackResult{mode,ticket}` + `rpc.identity.sso_exchange`. Produces: custom-domain session established via host-only cookies on the custom domain.

- [ ] **Step 1** — In `handleOAuthCallback` (login path), after `exchangeOAuthCode`, if `result.mode === "ticket"`: redirect to the origin's `/auth/sso?ticket=<result.ticket>&next=<result.redirect>` (origin allow-listed) — do NOT set cookies on the apex. Else keep the current cookie flow.

- [ ] **Step 2** — `auth/sso/route.ts` (runs ON the custom domain): read `ticket` + `next`; call `authService.ssoExchange(ticket)` → `{access_token, refresh_token}`; set **host-only** `owt_access_token`/`owt_refresh_token` (no `domain`, since this is a foreign registrable domain), `path:/`, sameSite lax, secure prod, maxAge as in the callback; redirect to `safeRedirectTarget(next, currentOrigin)`. On failure → error redirect. Reuse the cookie/maxAge constants from `oauth-callback.ts` (export them or a shared `auth-cookies` const).

- [ ] **Step 3: Verify + commit** — `bunx tsc` clean; `git commit -m "feat(oauth): /auth/sso ticket handoff sets host cookies on custom domain"`

---

### Task 10: Custom-domain account-linking via a single-use provider-identity ticket

**Shipped design (supersedes the "signed link-intent" sketch this task started from):** the original plan below minted a signed `link_intent` from the custom-domain-readable access token and carried it in the OAuth state. That was reverted for a security flaw — an attacker could mint their own `link_intent`, capture it, and lure a victim's live bearer session into completing the link, attaching the ATTACKER's provider identity to the VICTIM's account. The shipped design instead crosses the apex↔custom-domain boundary with a single-use Redis ticket that carries ONLY the just-exchanged OAuth PROVIDER identity — never a site user id. The linked-to site account is resolved from the LIVE session on the custom domain, at `/auth/link/complete`, never from the ticket. Cross-domain tickets are additionally bound by a host-only `owt_xdomain_guard` cookie (constant-time hash-compared at redemption), closing the same hijack shape at the transport level too.

**Files (shipped):**
- `backend/identity-service/src/services/pending_link_tickets.py` (one-time Redis ticket, `GETDEL`-redeemed at most once, TTL 120s, provider identity only — mirrors `sso_tickets` with the roles reversed)
- `backend/identity-service/src/services/oauth_flows.py` (`link` mints the ticket at the apex callback; `link_complete` redeems it against the caller's live session + guard cookie), `oauth_service.py`
- `frontend/src/lib/oauth-login.ts` (`onCustomDomain` branch sets the host-only `owt_xdomain_guard` cookie before bouncing to the apex), `oauth-callback.ts`
- `frontend/src/app/(site)/auth/link/complete/route.ts` (redeems the ticket on the custom domain against ITS OWN live local session; never establishes a session from the ticket itself)

**Interfaces (shipped):**
- Produces/consumes: a single-use Redis ticket (`link:ticket:<code>`) carrying `{oauth_info, token_data}` — the exchanged provider identity, never a site user id. Site identity is resolved from the live session on the custom domain at `/auth/link/complete`. A host-only `owt_xdomain_guard` cookie binds the cross-domain ticket to the browser that started the flow.

- [x] Shipped as described above; see `pending_link_tickets.py`'s module docstring ("Task 10R") for the full security rationale, and `docs/superpowers/plans/2026-07-06-subdomains-ops-runbook.md` step 6 for the operational verification (`/auth/link/complete` requires an existing session on that exact host and never establishes a new one from the ticket).

---

### Task 11: Dynamic WS origin validation for custom domains (gateway)

**Files:**
- Modify: `gateway/internal/ws/handler.go`
- Modify: `gateway/internal/workspace/workspace.go` (add `IsAllowedWSOrigin(ctx, originHost) bool` — apex/`*.owt`/verified custom domain)
- Test: `gateway/internal/ws/origin_test.go` (extend)

**Interfaces:**
- Consumes the workspace-host set (DB/cache). Produces: WS Accept allows same-host + `*.owt`/apex + verified custom domains, per-request; never `InsecureSkipVerify`.

- [ ] **Step 1** — Add a host-check on the workspace resolver: `IsVerifiedCustomDomain(ctx, host) (bool, error)` (query `workspace WHERE custom_domain=$1 AND custom_domain_verified_at IS NOT NULL`, cached with a short TTL like the other gateway lookups).
- [ ] **Step 2** — In `ServeHTTP`, before `websocket.Accept`: read the `Origin` header; if empty → same-origin (Accept with the static patterns). Else parse the origin host: if it matches the static `*.owt`/apex patterns → use the static `h.accept`. Else look up `IsVerifiedCustomDomain(host)`; if true → `websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: append(staticPatterns, originHost)})`; if false → reject (let the static Accept fail it). Keep `InsecureSkipVerify` unset throughout.
- [ ] **Step 3: Test** — a verified-custom-domain origin is accepted (with a stub resolver returning true), a foreign origin rejected. `cd gateway && go test ./internal/ws/...`.
- [ ] **Step 4: Commit** — `git commit -m "feat(ws): allow verified custom-domain origins dynamically"`

---

### Task 12: On-demand TLS + env + ops runbook (external Traefik)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-06-subdomains-ops-runbook.md` (add a Custom Domains section) or a new `2026-07-06-custom-domains-ops.md`.
- Modify: env examples if any new var is introduced (none expected).

**Interfaces:** none (docs/ops).

- [ ] **Step 1** — Document, with exact records: customer adds TXT `_owt-verify.<domain>` = `<token>` + CNAME/A `<domain> → owt.craazzzyyfoxx.me`; organiser clicks Verify (Task 5). Traefik: an on-demand HTTP-01 cert per custom domain — a catch-all HTTPS router (`HostRegexp(...)` broad or Traefik on-demand TLS) with `certResolver` using HTTP-01 (works once the customer's DNS points at the ingress). Note LE per-domain rate limits are per-customer-domain (fine). Verify checklist: DNS → verify passes → TLS issues → host resolves to the workspace → OAuth login round-trips via ticket handoff → session cookie is host-only on the custom domain.
- [ ] **Step 2: Commit** — `git commit -m "docs(custom-domains): ops runbook (verification, on-demand TLS)"`

---

### Task 13: End-to-end verification

- [ ] Backend: `uv run pytest` (hostnames, custom-domain, sso-tickets, oauth-state, by_host) green.
- [ ] Gateway: `go build/vet/test` green (WS custom-origin test).
- [ ] Frontend: `bun test` + `tsc`/`eslint` clean.
- [ ] Manual E2E (needs a real custom domain + DNS + on-demand TLS): set + verify a custom domain in admin; visit it → resolves to the workspace (white-label); OAuth login → bounces to apex → ticket handoff → host-only cookies on the custom domain, session works; WS connects; apex + subdomains unaffected; unverified/unknown host → 404.

## Self-Review

**Spec coverage (Phase 2):** custom_domain columns → T1; verification (TXT/CNAME + DNS check) + settings UI → T5; on-demand TLS → T12; SSO ticket handoff (`sso_exchange` + `/auth/sso` + Redis) → T8/T9; dynamic WS origin → T11; resolver matches verified custom_domain → T2/T3/T4; custom-domain account-linking via a single-use provider-identity ticket (`owt_xdomain_guard`-bound) → T10; origin validation → T6; apex-bounce for CSRF → T7.

**Placeholder scan:** T6 carries an explicit *decision/fallback* (validate platform hosts now) — a scoping call with a defined safe default, not a TODO. T10 shipped in full (see above) rather than falling back to its original scoping decision.

**Type consistency:** `resolveHost` returns `{mode:"tenant", host}` (T4) consumed by middleware (T4) + callers; `OAuthCallbackResult{mode, ticket?}` produced T8, consumed T9; `by_host` shape unchanged (`{workspace_id, slug}`) T3; `normalize_custom_domain`/`is_platform_host` (T2) used in T3/T5/T6/T8.

## Notes / risks
- **`resolveHost` return-shape change** (`subdomain` → `host`) is a breaking change to a Phase-1 file; T4 must update all callers (`middleware.ts`, `WorkspaceBootstrap.tsx`, `oauth-callback.ts`).
- identity-svc doesn't own the workspace DB; T6 origin validation is limited to platform hosts unless a workspace-host lookup is wired — documented, fail-closed.
- On-demand per-domain TLS is external Traefik (T12) — the only out-of-repo dependency.
