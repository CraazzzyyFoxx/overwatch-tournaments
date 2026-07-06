# Workspace multi-domain (subdomains + custom domains) — design

- **Date:** 2026-07-06
- **Status:** Draft (awaiting review)
- **Related:** per-workspace branding ([[project_workspace_branding]], `lib/workspace-theme.ts`), plan `distributed-sleeping-parrot.md`

## Context & motivation

Per-workspace branding (custom palette) shipped, but every workspace still lives under one shared host with the workspace chosen by a cookie (`owt-workspace-id`). Organisers want true white-label presence: a workspace reachable at its own **subdomain** (`team-a.owt.craazzzyyfoxx.me`) and/or its own **custom domain** (`tourney.customer.com`), where the host *is* the workspace.

The pressing blocker is **OAuth**: the OAuth `redirect_uri` is a single hardcoded value and providers (Discord/Twitch/Battle.net) don't allow wildcard redirect URIs, so login can't round-trip on arbitrary hosts. This spec solves OAuth plus the surrounding host-awareness (resolver, cookies, SEO, WebSockets, TLS).

## Decisions (locked)

1. **Scope:** design both subdomains *and* custom domains; implement phased (subdomains = Phase 1, custom domains = Phase 2).
2. **Host↔workspace:** hard white-label lock. On a tenant host the whole site is scoped to that one workspace (host overrides cookie, switcher + "all communities" hidden). The apex `owt.craazzzyyfoxx.me` stays the multi-workspace platform.
3. **Subdomain provisioning:** opt-in, dedicated `subdomain` column (nullable, unique, strict DNS label), independent of `slug`.
4. **Custom domain:** opt-in `custom_domain` column + DNS verification.
5. **SEO:** dedicated `seo_title` / `seo_description` columns (default to `name`/`description`); favicon + OG image from `icon_url`. On tenant hosts these override the platform `SITE_NAME`.
6. **Platform zone:** `owt.craazzzyyfoxx.me` — apex is the platform; subdomains `*.owt.craazzzyyfoxx.me`; session cookies scoped `Domain=.owt.craazzzyyfoxx.me`; single OAuth callback `https://owt.craazzzyyfoxx.me/auth/callback`.

## Goals / non-goals

**Goals:** host→workspace resolution; white-label lock; OAuth working on any host; SSO across subdomains + cross-domain handoff for custom domains; per-host SEO with workspace branding; WS origin safety; custom-domain verification.

**Non-goals (this spec):** per-workspace email/SMTP domains; per-workspace OAuth *apps* (all workspaces share the platform's provider apps); multi-region; changing the workspace RBAC model.

## Architecture

### A. Hosts & routing (mostly already host-agnostic)

- nginx is a catch-all (`server_name _`, forwards `Host`/`X-Forwarded-Proto`, `nginx/nginx.conf:61,78,81`) and the Go gateway forwards Host untouched (`gateway/internal/proxy/proxy.go:67-69`). **No nginx/gateway routing changes needed** — any host already reaches the app.
- **TLS = external Traefik (ops dependency, not in repo).** Needs: wildcard for `*.owt.craazzzyyfoxx.me` (DNS-01 ACME, one cert — avoids LE rate limits) and on-demand per-domain certs for custom domains (HTTP-01, issued once the customer points DNS at the ingress). This is the only piece living outside the codebase.

### B. Data model — `Workspace` (`backend/shared/models/tenancy/workspace.py`)

New typed columns (additive migration, e.g. `wsdomain0001`):

| Column | Type | Notes |
|---|---|---|
| `subdomain` | `str \| None` | unique, `^[a-z0-9-]+$` (strict DNS label, no `_`), reserved-label blocklist |
| `custom_domain` | `str \| None` | unique, lowercased FQDN |
| `custom_domain_verified_at` | `datetime \| None` | resolver matches domain only when set (fail-closed) |
| `custom_domain_verification_token` | `str \| None` | value for the DNS TXT record |
| `seo_title` | `str \| None` | default → `name` |
| `seo_description` | `str \| None` | default → `description` |

Reserved subdomain labels (cannot be claimed): `www`, `api`, `auth`, `admin`, `app`, `assets`, `static`, `cdn`, `mail`, `ws`. **Canonical host** (computed, not stored): `custom_domain` if verified → else `subdomain`.`owt.craazzzyyfoxx.me` → else apex `/workspace/{slug}`.

Schemas: add fields to `WorkspaceRead` + `WorkspaceUpdate` (`backend/app-service/src/schemas/workspace.py`) with validators. Update path stays the generic CRUD engine (no new RPC for writes). Frontend `Workspace` type mirrors them (`frontend/src/types/workspace.types.ts`).

### C. Host → workspace resolver

- **New backend RPC** `rpc.app.workspaces.by_host` (`backend/app-service/src/rpc/workspaces.py`, public + cached): given a host, returns `{workspace_id, slug}` matching `subdomain` (under the platform zone) or a **verified** `custom_domain`. Backed by new indexed lookups (reuse the `get_by_slug` pattern in `services/workspace/service.py:36`).
- **New `frontend/src/middleware.ts`:** reads `x-forwarded-host`. Apex/`www` → platform mode (no forced workspace). Tenant host → call `by_host` (aggressively cached: small, rarely-changing map; TTL + invalidate on domain change) → inject `x-owt-workspace-id` request header via `NextResponse.rewrite`. Unknown/unverified tenant host → 404 "not configured" page (never silently fall through to the apex platform).
- **Scope precedence:** `getServerWorkspaceId` (`frontend/src/lib/api-fetch.ts:77-85`) prefers the middleware header over the cookie (host beats cookie = white-label lock). Apex → no header → existing cookie behaviour. SSR branding seed (`app/(site)/layout.tsx:13-24`) resolves from the header on tenant hosts.
- **White-label UI:** in tenant mode hide `WorkspaceSwitcher` and the home "communities" list; the workspace-scoped chrome stays.

### D. OAuth (core) — single callback + signed state

The redirect_uri problem is solved by funnelling **every** provider round-trip through one registered callback and carrying the originating host in the (already stateless-HMAC) `state`.

1. **One registered `redirect_uri` per provider** = `https://owt.craazzzyyfoxx.me/auth/callback`, used for authorize *and* token exchange regardless of the tenant host the user started on. Replaces the single hardcoded `OAUTH_REDIRECT` semantics (`backend/identity-service/src/services/oauth_service.py:68/167/281`, config `core/config.py:77`) — the value becomes the fixed apex callback, no longer host-varying.
2. **Signed-state payload** (extend `oauth_service.py:464-500`): `{origin, action(login|link), provider, post_login_redirect, nonce, exp}`, HMAC-signed with `JWT_SECRET_KEY`. **CSRF defence = the signature alone** (drop the host-only `owt_oauth_state` cookie cross-check, which is unreadable on the callback host, `frontend/src/lib/oauth-login.ts:36`, `oauth-callback.ts:47,61`). `origin` is validated against the known workspace-host set. The transient action/provider/redirect cookies are folded into the state too (no cross-host cookie reliance).
3. **Start** (`startOAuthLogin`, `frontend/src/lib/oauth-login.ts`): records the current host as `origin` in state; clamps `post_login_redirect` to the origin host (not the single `SITE_URL`).
4. **Callback** (`frontend/src/app/(site)/auth/callback/route.ts`, `lib/oauth-callback.ts`): validate signed state (HMAC + exp + nonce + origin allow-list), exchange code, mint access+refresh JWTs (unchanged — JWTs are already host-agnostic, `gateway/internal/auth/auth.go:61-85`), then deliver the session to `origin`:
   - **Subdomain / apex origin** → set `owt_access_token` / `owt_refresh_token` with **`Domain=.owt.craazzzyyfoxx.me`** → immediately valid on the origin subdomain (SSO across all subdomains). Redirect to `https://{origin}{post_login_redirect}`.
   - **Custom-domain origin** → cookies can't cross registrable domains → **one-time SSO ticket**: identity-svc mints an opaque code in Redis (TTL ~60s, single-use), redirect to `https://{custom}/auth/sso?ticket=...`.
5. **SSO handoff endpoint** (new `frontend/src/app/(site)/auth/sso/route.ts`, Phase 2): reads `ticket`, calls new `rpc.identity.sso_exchange` (redeems the one-time code server-side → returns the token pair), sets **host** cookies on the custom domain, redirects to the destination. Refresh token never appears in a URL.

### E. Session / cookie strategy

- **Cookie naming (aqt→owt rebrand, back-compat):** cookies are written under the new `owt_*` names (`owt_access_token`, `owt_refresh_token`, `owt-workspace-id`, `owt_oauth_*`) but **read as `owt_* ?? aqt_*`** during migration, so existing `aqt_*` sessions are not logged out. Every read site gets the fallback; every write site uses `owt_*` only. The `aqt_*` fallback is removed in a later cleanup. Read/write sites: gateway `internal/auth/auth.go:21` (name constant + read order), `frontend/src/lib/{oauth-callback,auth-tokens}.ts`, `auth/refresh/route.ts`, `stores/workspace.store.ts`, and `api-fetch.ts:77-85`.
- Subdomains + apex: `Domain=.owt.craazzzyyfoxx.me` on `owt_access_token` (js-readable), `owt_refresh_token` (httpOnly), `owt-workspace-id`. Set in `frontend/src/lib/oauth-callback.ts:87-101`, `auth/refresh/route.ts:26-40`, `lib/auth-tokens.ts:46-51`, `stores/workspace.store.ts:71`.
- Custom domains: host-only cookies on that domain, established via the SSO handoff (E.4/D.5). Each custom domain is an independent session island.
- **Logout:** on subdomains/apex, clear the `.owt.craazzzyyfoxx.me` cookies → **global logout across all subdomains** (accepted). On a custom domain, clear that host's cookies only (`frontend/src/app/(site)/auth/logout/route.ts`).
- **Account linking from a custom domain** (Phase 2 nuance): the callback can't read the custom-domain auth cookie to know who is linking → carry a short-lived signed "link intent" (user id) in the state.

### F. Custom-domain verification (Phase 2)

1. Organiser enters `custom_domain` in settings → stored unverified + `custom_domain_verification_token` generated.
2. UI shows: TXT `_anak-verify.<domain> = <token>` and CNAME/A `<domain> → owt.craazzzyyfoxx.me`.
3. "Verify" → backend DNS TXT lookup → set `custom_domain_verified_at`. Resolver only serves verified domains.
4. TLS issued on-demand by external Traefik once DNS points at the ingress.

### G. SEO / per-host metadata

- Replace static `SITE_NAME`/`SITE_URL`/hardcoded `metadataBase` with **per-request, per-workspace** metadata. Root `layout.tsx` (`:35-50`) and section layouts (`app/(site)/{owal,statistics,encounters,matches,teams,tournaments,tournaments/analytics}/layout.tsx:8`, plus `users/*`) switch static `metadata` → async `generateMetadata` that resolves the host's workspace (via the middleware header + a cached fetch).
- On tenant hosts: `title`/OG `siteName` = `seo_title ?? name`; `description` = `seo_description ?? description`; `icons.icon` (favicon) + OG image = `icon_url` (fallback to platform `/favicon.ico`, `/logo.webp`); `metadataBase`/canonical = the tenant host origin (host helper modelled on `getServerRequestOrigin`, `api-fetch.ts:87-109`).
- `sitemap.ts` / `robots.ts` become host-scoped (emit only the current host / that workspace's URLs). Apex keeps platform-wide defaults.

### H. WebSockets

`GATEWAY_WS_ALLOWED_ORIGINS` (static CSV, `gateway/internal/config/config.go:130`, enforced `gateway/internal/ws/handler.go:47-58`) can't enumerate custom domains. Change the WS origin check to **dynamic validation**: allow the `*.owt.craazzzyyfoxx.me` pattern (subdomains) + validate other origins against the known workspace-host set (same lookup as the resolver). Never fall back to `InsecureSkipVerify`.

## Phasing

**Phase 1 — Subdomains**
- `subdomain` + `seo_*` columns + migration; schema + type updates; admin/settings editor (toggle + field + reserved-label validation).
- `by_host` RPC (subdomain match) + `frontend/src/middleware.ts` + header-based scope precedence + white-label UI gating.
- OAuth: single apex callback + signed-state (origin/action/provider/redirect in state, drop state-cookie cross-check) + `Domain=.owt.craazzzyyfoxx.me` cookies.
- Per-host SEO (workspace-branded metadata) + host-aware sitemap/robots.
- WS origin `*.owt.craazzzyyfoxx.me`.
- Ops: wildcard DNS `*.owt.craazzzyyfoxx.me` + wildcard TLS (DNS-01) in Traefik.

**Phase 2 — Custom domains**
- `custom_domain` + verification columns; verification flow (TXT/CNAME + DNS check) + settings UI.
- On-demand per-domain TLS (Traefik).
- SSO ticket handoff: `rpc.identity.sso_exchange` (Redis one-time code) + `auth/sso` route + host-cookie set on custom domain.
- Dynamic WS origin validation for custom domains.
- Resolver matches verified `custom_domain`; custom-domain account-linking via signed link-intent.

## Security considerations

- Signed-state CSRF: HMAC over `{origin, nonce, exp}` is unforgeable and is the standard stateless-CSRF pattern; short `exp` + single-use `nonce` (Redis) prevent replay. `origin` validated against the workspace-host allow-list (no open redirect).
- SSO ticket: opaque, single-use, ~60s TTL, deleted on redemption, exchanged server-side (never carries the refresh token in a URL).
- `owt_access_token` stays js-readable but with `Domain=.owt.craazzzyyfoxx.me` is exposed only to our own subdomains (trust boundary); custom domains get isolated host cookies.
- Reserved-label + verified-only custom-domain matching prevent host takeover / squatting.

## Edge cases

- Unknown/unverified tenant host → 404 "not configured" page (no fall-through to apex).
- Anonymous session on a custom domain → must log in there (no cross-domain cookie) → handled by ticket handoff on next login.
- `subdomain`/`custom_domain` changed → invalidate resolver cache; old host 404s.
- Slug change no longer affects the URL (subdomain is a separate column).
- Apex + `www` always platform mode.

## Testing

- **Unit:** host→workspace resolver (subdomain/custom/apex/unknown/reserved); signed-state encode/decode (origin+action+exp+nonce, tamper rejection, origin allow-list); SSO ticket (single-use + expiry); host-origin + per-workspace metadata helpers; reserved-label + DNS-label validators.
- **Integration:** `by_host` RPC; OAuth callback cookie-domain selection (subdomain vs custom); `sso_exchange` redemption.
- **E2E/manual:** login on a subdomain (SSO carries across subdomains); login on a custom domain (ticket handoff sets host cookies); white-label lock (no switcher / no communities); per-host canonical + workspace-branded title/favicon; WS connect from a tenant host; unknown host → apex.

## External dependencies / open items

- **Traefik (ops):** wildcard DNS + wildcard TLS for `*.owt.craazzzyyfoxx.me`; on-demand per-domain ACME for custom domains. Config lives outside this repo — needs ops access.
- **OAuth provider consoles:** register the single `https://owt.craazzzyyfoxx.me/auth/callback` redirect URI for Discord/Twitch/Battle.net.

## Key affected files

- Backend: `shared/models/tenancy/workspace.py`, `app-service/src/schemas/workspace.py`, `app-service/src/rpc/workspaces.py`, `app-service/src/services/workspace/service.py`, `identity-service/src/services/oauth_service.py`, `identity-service/src/core/config.py`, new migration.
- Frontend: new `middleware.ts`, `lib/api-fetch.ts`, `lib/oauth-login.ts`, `lib/oauth-callback.ts`, `app/(site)/auth/{callback,logout,sso}/route.ts`, `config/site.ts`, root + section `layout.tsx` (generateMetadata), `sitemap.ts`, `robots.ts`, `components/WorkspaceSwitcher.tsx` + home communities, admin/settings workspace editor, `types/workspace.types.ts`.
- Gateway: `internal/ws/handler.go`, `internal/config/config.go`.
