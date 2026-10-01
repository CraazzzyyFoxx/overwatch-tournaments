# Workspace Subdomains & Custom Domains: Ops Runbook

**Platform Zone:** `owt.craazzzyyfoxx.me`

This document describes the out-of-repo operational steps required to enable workspace multi-domain support. Sections 1-4 cover platform-zone subdomains (wildcard DNS-01 TLS). **Section 5 covers customer-owned custom domains (per-domain HTTP-01 TLS)** — read Section 2 first, since Section 5 builds on the same TLS edge rather than re-explaining it.

---

## 1. DNS Records

### Wildcard A Record
Create a wildcard DNS record that resolves all tenant subdomains to the ingress IP:

```
*.owt.craazzzyyfoxx.me  A  <INGRESS_IP>
```

**Where to configure:** Your DNS provider (CloudFlare, Route53, etc.)  
**TTL:** 300 seconds (or provider default)  
**Value:** Replace `<INGRESS_IP>` with the actual IP address of your ingress (the TLS terminator in front of nginx).

### Apex Record
Ensure the apex domain also resolves:

```
owt.craazzzyyfoxx.me  A  <INGRESS_IP>
```

**Purpose:** Allows direct access to `https://owt.craazzzyyfoxx.me` (the primary platform zone), as well as workspace subdomains (`<workspace>.owt.craazzzyyfoxx.me`).

### Verification
```bash
# Verify wildcard resolves
nslookup test-tenant.owt.craazzzyyfoxx.me
nslookup owt.craazzzyyfoxx.me

# Expected output: both should return <INGRESS_IP>
```

---

## 2. TLS / HTTPS

TLS is terminated outside the stack, in front of nginx. nginx and the gateway receive plain HTTP and hold no certificates. The terminator must pass `Host` through unchanged (the workspace is resolved from it) and set `X-Forwarded-For` and `X-Forwarded-Proto`; nginx trusts `X-Forwarded-For` only from private ranges and loopback.

Certificates it needs:

| Certificate | Challenge | Why |
|---|---|---|
| `owt.craazzzyyfoxx.me` + `*.owt.craazzzyyfoxx.me`, one certificate with both SANs | DNS-01 | a wildcard can only be issued over DNS-01 |
| each verified custom domain (Section 5) | HTTP-01 | we have no API access to a customer's DNS |

```bash
echo | openssl s_client -connect owt.craazzzyyfoxx.me:443 -servername owt.craazzzyyfoxx.me 2>/dev/null \
  | openssl x509 -noout -subject -enddate
```

---

## 3. OAuth Provider Registration

Each OAuth provider (Discord, Twitch, Battle.net) requires the **single redirect URI** to be registered in their developer console.

### Redirect URI
```
https://owt.craazzzyyfoxx.me/auth/callback
```

**Note:** This is the **only** callback for all tenants. The identity-svc validates the session and workspace context internally; the OAuth flow always returns to this canonical URL.

### Discord Developer Console

1. Go to https://discord.com/developers/applications
2. Select or create your application
3. Navigate to **OAuth2 > General**
4. Under **Redirects**, add:
   ```
   https://owt.craazzzyyfoxx.me/auth/callback
   ```
5. Save and note the **Client ID** and **Client Secret** → environment variables (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` in `backend/env/auth.env`)

### Twitch Developer Console

1. Go to https://dev.twitch.tv/console/apps
2. Select or create your application
3. Navigate to **OAuth Redirect URLs**
4. Add:
   ```
   https://owt.craazzzyyfoxx.me/auth/callback
   ```
5. Save and note **Client ID** and **Client Secret** → environment variables (`TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`)

### Battle.net Developer Console

1. Go to https://develop.battle.net/applications
2. Select or create your application
3. Navigate to **OAuth**
4. Under **Redirect URIs**, add:
   ```
   https://owt.craazzzyyfoxx.me/auth/callback
   ```
5. Save and note **Client ID** and **Client Secret** → environment variables (`BATTLENET_CLIENT_ID`, `BATTLENET_CLIENT_SECRET`)

### Environment Variables

Update `backend/env/auth.env` (or `.env.production` for Docker) with:

```bash
DISCORD_CLIENT_ID=<your-discord-client-id>
DISCORD_CLIENT_SECRET=<your-discord-client-secret>

TWITCH_CLIENT_ID=<your-twitch-client-id>
TWITCH_CLIENT_SECRET=<your-twitch-client-secret>

BATTLENET_CLIENT_ID=<your-battlenet-client-id>
BATTLENET_CLIENT_SECRET=<your-battlenet-client-secret>
BATTLENET_REGION=eu

OAUTH_REDIRECT=https://owt.craazzzyyfoxx.me/auth/callback
```

---

## 4. Verification Checklist

After DNS, TLS, and OAuth provider registration are complete, run the following checks:

### [ ] DNS Resolution

```bash
# Verify wildcard resolves
nslookup dev.owt.craazzzyyfoxx.me
nslookup prod.owt.craazzzyyfoxx.me
nslookup owt.craazzzyyfoxx.me

# Expected: all return <INGRESS_IP>
```

### [ ] TLS Certificate

```bash
# Check certificate validity for the apex and a subdomain
curl -vI https://owt.craazzzyyfoxx.me/api/health
curl -vI https://test-tenant.owt.craazzzyyfoxx.me/api/health

# Expected:
# - HTTP/2 200 or 3xx
# - Subject: CN = *.owt.craazzzyyfoxx.me (in certificate details)
# - Issuer: Let's Encrypt
```

### [ ] OAuth Login Round-Trip

1. Navigate to `https://owt.craazzzyyfoxx.me` in a browser
2. Click **Login** → select **Discord** (or Twitch/Battle.net)
3. Approve scopes in the OAuth provider's consent screen
4. Verify you are redirected back to `https://owt.craazzzyyfoxx.me/auth/callback`
5. Check that you are authenticated and can see your profile

### [ ] Subdomain Login & Cookie Propagation

1. Create or navigate to a workspace accessible at `https://<workspace>.owt.craazzzyyfoxx.me`
2. Verify the page loads (workspace resolver accepts the subdomain)
3. Perform an OAuth login as above
4. Verify that cookies are set with the domain `.owt.craazzzyyfoxx.me` (domain-wide, not subdomain-specific):
   - Browser DevTools > Application > Cookies
   - Look for `owt_access_token`, `owt_refresh_token`, `owt-workspace-id`
   - Each should have **Domain: `.owt.craazzzyyfoxx.me`** (leading dot)
5. Navigate to another subdomain (e.g., `https://<other-workspace>.owt.craazzzyyfoxx.me`)
6. Verify that you remain logged in (session carries across subdomains)

### [ ] WebSocket Origin Validation

1. Open browser DevTools > Network > WS (filter for WebSocket)
2. On the workspace subdomain, perform any action that opens a WebSocket (e.g., real-time updates)
3. Verify the WebSocket connects successfully (not rejected with 403 Forbidden)
4. Check that the gateway accepted the `Origin` header from the subdomain

### Summary

If all checks pass:
- ✅ DNS wildcards and apex resolve correctly
- ✅ TLS certificate covers `*.owt.craazzzyyfoxx.me` and is valid
- ✅ OAuth callbacks work and redirect to the canonical URL
- ✅ Workspace subdomains resolve and load
- ✅ Sessions propagate across subdomains
- ✅ WebSocket connections are allowed

---

## 5. Custom Domains

Custom domains let a workspace serve on a domain the *customer* owns and controls DNS for (e.g. `tourney.example.com`), instead of (or alongside) a `*.owt.craazzzyyfoxx.me` subdomain. Because we don't control the customer's DNS, this is a materially different ops story from Section 2's wildcard: verification is DNS-TXT-based ownership proof, and TLS is issued **on demand per domain via HTTP-01**, not the shared DNS-01 wildcard.

All record names, token formats, and gates below are quoted from the actual implementation — see the file:line references — not assumed.

### 5.1 What the code actually does (source of truth)

- **Verification token generation** — `backend/app-service/src/services/workspace/service.py`:
  ```python
  _CUSTOM_DOMAIN_TOKEN_PREFIX = "owt-verify-"
  ...
  token = _CUSTOM_DOMAIN_TOKEN_PREFIX + secrets.token_urlsafe(24)
  ```
  The stored token is always `owt-verify-<url-safe-random-string>` — copy it byte-for-byte from the admin UI; there is no way to recover/regenerate the same token without calling `set_custom_domain` again (which also resets `custom_domain_verified_at` to unverified).

- **DNS TXT record checked** — `verify_custom_domain`, `service.py`:
  ```python
  ok = await _dns_txt_contains(
      f"_owt-verify.{workspace.custom_domain}", workspace.custom_domain_verification_token
  )
  ```
  The record queried is **`_owt-verify.<custom_domain>`** (a dedicated subrecord under the customer's domain) — **not** a TXT on the apex of the customer's domain. `_dns_txt_contains` (`service.py`) does a live `dns.asyncresolver.resolve(name, "TXT")` lookup and fails closed (any DNS error → not verified, never a 500).

- **Domain normalization/guardrails** — `backend/shared/tenancy/hostnames.py` (`normalize_custom_domain`): lowercases, strips port/trailing dot, requires a valid multi-label FQDN, and explicitly rejects anything under the platform zone (`owt.craazzzyyfoxx.me` or a subdomain of it) — a customer cannot claim a domain that collides with a workspace subdomain.

- **Resolver fail-closed** — `get_by_verified_custom_domain` (`backend/shared/repository/workspace.py`) only matches rows where `custom_domain_verified_at IS NOT NULL`. A domain that is set-but-unverified never resolves to a workspace, in `by_host`, in the gateway's WS origin check, or anywhere else.

### 5.2 Customer DNS records

Two records, two different purposes — give the customer **both**, but understand they gate different things:

| Record | Name | Value | Purpose |
|---|---|---|---|
| TXT | `_owt-verify.<custom-domain>` | The exact token shown in admin, e.g. `owt-verify-<random>` | **Ownership verification only.** Read once by "Verify"; not consulted again after `custom_domain_verified_at` is set. Can be removed after verification if the customer wants (re-verification, e.g. after `clear_custom_domain` + re-`set_custom_domain`, would need it added back). |
| CNAME (or A, if the domain is an apex and the registrar doesn't allow CNAME-at-apex) | `<custom-domain>` | `owt.craazzzyyfoxx.me` (CNAME) or the ingress IP (A record — same IP as Section 1's wildcard `A` record) | **Serving traffic + TLS issuance.** Must resolve to the ingress before the HTTP-01 challenge (Section 5.3) can succeed, and before real visitors reach the site. |

Both records are exactly what the admin UI (`frontend/src/app/admin/workspaces/page.tsx`) displays to the organiser once a custom domain is saved (unverified):

```
TXT   _owt-verify.tourney.example.com   owt-verify-<random-token>
CNAME tourney.example.com               owt.craazzzyyfoxx.me
```

Verification (Step 5.4 below) only needs the TXT record. Real traffic and TLS need the CNAME/A record. They can be added at the same time — there's no ordering requirement between them.

### 5.3 TLS: an HTTP-01 certificate per custom domain

Section 2's DNS-01 certificate covers only the platform zone. A customer's domain gets its own certificate over HTTP-01: we never have API access to a customer's DNS, and HTTP-01 needs only the CNAME/A record from Section 5.2 plus an answer at `http://<domain>/.well-known/acme-challenge/...` from the TLS terminator.

Once the domain is verified and resolves to us, issue its certificate on the terminator and keep it renewed.

Routing needs nothing: the terminator sends every host to nginx, and the workspace is resolved from the Host header. Until the certificate exists the domain is served the platform certificate and browsers warn.

To drop a domain, remove its certificate from the terminator.

**Let's Encrypt rate limits:** the "Certificates per Registered Domain" limit (currently 50/week, per LE's published limits — https://letsencrypt.org/docs/rate-limits/) is scoped to *the customer's own registered domain*, not to us — onboarding N customers does **not** share or exhaust a single aggregate budget across tenants the way the shared wildcard would. The one limit that *is* shared across all custom domains is the "New Orders per Account per 3 hours" cap (currently 300), since every order goes through the same ACME account as the wildcard — fine at the expected scale (a handful to low dozens of custom domains).

### 5.4 Organiser steps (Admin UI)

1. Navigate to `/admin/workspaces` (gated: visible to `isSuperuser` or `isWorkspaceAdmin(workspace_id)` in the UI; **authoritatively enforced server-side** on every RPC by `ensure_workspace_permission(user, workspace_id, "workspace", "update")` in `backend/app-service/src/rpc/workspaces.py` — i.e. workspace owner/admin roles or a platform superuser).
2. Click **Edit** on the target workspace → scroll to **Domain & SEO** → **Custom domain** field.
3. Enter the domain (e.g. `tourney.example.com`) → click **Save**. This calls `POST /api/v1/workspaces/{workspace_id}/custom-domain` (`rpc.app.workspaces.set_custom_domain`), which stores the normalized domain plus a fresh `owt-verify-...` token and resets `custom_domain_verified_at` to unset. The UI flips to a **"Pending verification"** badge and shows the TXT + CNAME records to add (Section 5.2).
4. Give the customer the two DNS records; they add them at their registrar/DNS provider.
5. Once DNS has propagated, click **Verify**. This calls `POST /api/v1/workspaces/{workspace_id}/custom-domain/verify` (`rpc.app.workspaces.verify_custom_domain`), which does the live `_owt-verify.<domain>` TXT lookup. On success the badge flips to **"Verified"** and the domain input locks (with a **Remove** button in its place). On failure the UI shows: *"Verification record not found yet — DNS changes can take time to propagate"* — just retry Verify after DNS propagates; there's no separate retry limit or cooldown in the code.

### 5.5 End-to-end verification checklist

Run these in order — each is independently checkable, and later steps assume earlier ones already pass.

1. **Customer DNS is live**
   ```bash
   dig TXT _owt-verify.tourney.example.com +short     # expect: "owt-verify-<token>"
   dig CNAME tourney.example.com +short               # expect: owt.craazzzyyfoxx.me.
   # (or `dig A tourney.example.com +short` if an A record was used instead)
   ```
2. **Admin "Verify" passes** — the workspace's `custom_domain_verified_at` is non-null (visible as the "Verified" badge in the admin UI, or via `GET /api/v1/workspaces/{workspace_id}`).
3. **TLS cert issues** — `curl -vI https://tourney.example.com` returns a Let's Encrypt-issued cert for exactly that host (not the wildcard's SAN list), no cert warnings.
4. **Host resolves to the workspace** — the page loads with that workspace's white-label chrome, and:
   ```bash
   curl "https://owt.craazzzyyfoxx.me/api/v1/workspaces/by-host?host=tourney.example.com"
   # expect: {"data": {"workspace_id": <id>, "slug": "..."}, ...}
   ```
   Note the frontend (`frontend/src/proxy.ts`) and this RPC both cache host→workspace lookups for up to 60 seconds (`CACHE_TTL_MS = 60_000`); allow up to a minute after verification before this check is guaranteed fresh.
5. **OAuth login round-trips.** From `https://tourney.example.com`, click Login. Confirm:
   - The browser is bounced to `https://owt.craazzzyyfoxx.me/auth/<provider>/login?origin=https://tourney.example.com&guard_hash=...` (`frontend/src/lib/auth/oauth-login.ts`'s `onCustomDomain` branch) — a host-only `owt_xdomain_guard` cookie is set on `tourney.example.com` *before* this bounce, carrying no `domain` attribute.
   - After provider consent, the apex callback redirects back to `https://tourney.example.com/auth/sso?ticket=...&next=...`.
   - `frontend/src/app/(site)/auth/sso/route.ts` redeems the ticket (requires the `owt_xdomain_guard` cookie set in the first bullet — fails closed with `invalid_state` if missing), sets `owt_access_token`/`owt_refresh_token` **host-only** (no `domain` attribute — these are NOT the `.owt.craazzzyyfoxx.me`-scoped subdomain cookies) on `tourney.example.com`, and clears the guard cookie.
6. **Account linking works.** From an *already-logged-in* session on `tourney.example.com`, use the "Link account" flow; confirm `/auth/link/complete` redeems the link ticket against the live local session (it requires an existing session on that exact host — `getAccessToken`/`loginRedirect` in `frontend/src/app/(site)/auth/link/complete/route.ts` — and never establishes a new session from the ticket itself).
7. **WS connects.** Open DevTools → Network → WS while on `tourney.example.com`; confirm the WebSocket handshake succeeds. The gateway's dynamic origin check (`gateway/internal/ws/handler.go`, backed by `gateway/internal/workspace/workspace.go`'s `IsVerifiedCustomDomain`) queries `custom_domain = $1 AND custom_domain_verified_at IS NOT NULL` and caches the result (verified or not) for 60 seconds (`customDomainCacheTTL`) per origin host.
8. **Apex + subdomains unaffected.** Re-run the Section 4 checklist against `https://owt.craazzzyyfoxx.me` and an existing `*.owt.craazzzyyfoxx.me` workspace — both must still resolve, serve TLS, and connect WS exactly as before.
9. **Unknown/unverified host → 404 / no workspace.** Hit a domain that was never `set_custom_domain`'d, and (separately) a domain that is `set_custom_domain`'d but not yet verified. Both must fail closed: `by_host` returns `data: null`, no white-label chrome loads, and the WS handshake from that origin is rejected — never silently mapped to any workspace.

### 5.6 Rollback / Clear

- **Unset a custom domain entirely:** `clear_custom_domain` (`DELETE /api/v1/workspaces/{workspace_id}/custom-domain`) wipes `custom_domain`, `custom_domain_verification_token`, and `custom_domain_verified_at` together. In the admin UI, the **Remove** button only appears once the domain is *verified*. For a domain that is still pending (saved but not yet verified), the UI's only exposed action is overwriting it via **Save** with a new value (which mints a fresh token and keeps the workspace unverified) — there's no dedicated "cancel" button for a pending, not-yet-verified domain. To fully clear a pending domain without replacing it, call the same endpoint directly: `DELETE /api/v1/workspaces/{workspace_id}/custom-domain` with a bearer token that has `workspace.update` for that workspace.
- **Propagation delay after any change:** both the gateway's WS-origin cache (`customDomainCacheTTL = 60 * time.Second`, `gateway/internal/workspace/workspace.go`) and the frontend's `by_host` middleware cache (`CACHE_TTL_MS = 60_000`, `frontend/src/proxy.ts`) mean a `set_custom_domain`, `verify_custom_domain`, or `clear_custom_domain` change can take **up to ~60 seconds** to take full effect for WS connections and page routing, even though the admin UI reflects the change immediately (it re-fetches the workspace directly, bypassing both caches).
- **Re-verifying after `clear_custom_domain` + re-`set_custom_domain`:** the token is regenerated every time `set_custom_domain` runs, so the customer must re-add the TXT record with the *new* token value — the old TXT value will no longer match.

---

## Rollback / Troubleshooting

### DNS Propagation Delay
If DNS changes don't resolve immediately:
- Wait 5–10 minutes for TTL expiry
- Flush local DNS cache: `ipconfig /flushdns` (Windows) or `sudo dscacheutil -flushcache` (macOS)
- Use `dig` or `nslookup` with a public resolver: `nslookup owt.craazzzyyfoxx.me 8.8.8.8`

### TLS Certificate Errors
- Check which certificate is served (the `openssl s_client` command in Section 2)
- A custom domain that gets the platform certificate has no certificate of its own yet (Section 5.3)

### OAuth Redirect Loop
- Verify `OAUTH_REDIRECT` in `backend/env/auth.env` matches the provider console entry exactly
- Check that provider credentials (`DISCORD_CLIENT_ID`, etc.) are correct
- Inspect gateway/identity-svc logs for state validation errors

### WebSocket Connection Refused
- Verify `GATEWAY_WS_ALLOWED_ORIGINS` in `backend/env/common.env.example` is set to include the workspace subdomain
- Restart the gateway service after env changes
- Check gateway logs for `Origin mismatch` or similar errors

---

## References

- **Let's Encrypt Rate Limits:** https://letsencrypt.org/docs/rate-limits/
- **OAuth 2.0 Redirect URI Security:** https://oauth.net/2/redirect-uris/
- **Custom-domain source of truth:** `backend/app-service/src/services/workspace/service.py` (`set_custom_domain`, `verify_custom_domain`, `_dns_txt_contains`), `backend/app-service/src/rpc/workspaces.py` (RPC gates), `backend/shared/tenancy/hostnames.py` (`normalize_custom_domain`), `gateway/internal/workspace/workspace.go` (`IsVerifiedCustomDomain`), `gateway/internal/ws/handler.go` (dynamic WS origin check), `frontend/src/app/admin/workspaces/page.tsx` (organiser UI), `frontend/src/lib/auth/oauth-login.ts` / `frontend/src/app/(site)/auth/sso/route.ts` / `frontend/src/app/(site)/auth/link/complete/route.ts` (OAuth apex-bounce + ticket handoff)
