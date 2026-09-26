# Workspace Subdomains & Custom Domains: Ops Runbook

**Date:** 2026-07-06 (Phase 1) / 2026-07-07 (Phase 2 addendum)
**Platform Zone:** `owt.craazzzyyfoxx.me`
**Phase:** 1 (subdomains, single OAuth callback) + 2 (customer-owned custom domains, on-demand TLS)

This document describes the out-of-repo operational steps required to enable workspace multi-domain support. Sections 1-4 cover Phase 1 (platform-zone subdomains, wildcard DNS-01 TLS). **Section 5 adds Phase 2 (customer-owned custom domains, on-demand HTTP-01 TLS)** — read Section 2 first, since Section 5 builds on the same external Traefik instance rather than re-explaining it.

---

## 1. DNS Records

### Wildcard A Record
Create a wildcard DNS record that resolves all tenant subdomains to the ingress IP:

```
*.owt.craazzzyyfoxx.me  A  <INGRESS_IP>
```

**Where to configure:** Your DNS provider (CloudFlare, Route53, etc.)  
**TTL:** 300 seconds (or provider default)  
**Value:** Replace `<INGRESS_IP>` with the actual IP address of your ingress/load balancer (the external IP that nginx/Traefik binds to).

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

## 2. TLS / HTTPS (External Traefik)

The TLS termination is handled by Traefik (external to the docker-compose stack, running on the production host). The Gateway and nginx services receive plain HTTP from Traefik and do not manage certificates.

### Wildcard Certificate via DNS-01 ACME

**Rationale:** A wildcard certificate for `*.owt.craazzzyyfoxx.me` covers all subdomains. To also cover the bare apex domain `owt.craazzzyyfoxx.me`, both the apex and the wildcard must be included as SANs (Subject Alternative Names) on the same certificate. This avoids Let's Encrypt's per-domain rate limits and simplifies multi-tenant DNS validation.

#### Prerequisites

1. **DNS API Credentials**: Your DNS provider must support API-driven ACME DNS-01 challenges.
   - Supported providers: CloudFlare, Route53, Azure DNS, Linode, DigitalOcean, etc.
   - Store credentials securely (e.g., in a `.env` file for Traefik).

2. **Traefik ACME Configuration** (host-level, `/root/overwatch-tournaments/traefik.yml` or equivalent):

```yaml
certificatesResolvers:
  dns-acme:
    acme:
      email: admin@example.com
      storage: ./acme.json
      dnsChallenge:
        provider: cloudflare  # or route53, azure, etc.
        resolvers:
          - 1.1.1.1:53
          - 8.8.8.8:53
      
      entryPoint: web  # or appropriate entrypoint
```

3. **Provider-Specific Environment Variables**: Add credentials for your DNS provider:

   **CloudFlare example:**
   ```bash
   export CF_API_EMAIL="your-email@example.com"
   export CF_API_KEY="your-global-api-key"
   # or
   export CF_DNS_API_TOKEN="your-dns-only-token"
   ```

   **Route53 example:**
   ```bash
   export AWS_ACCESS_KEY_ID="..."
   export AWS_SECRET_ACCESS_KEY="..."
   export AWS_REGION="us-east-1"
   ```

#### Certificate Issuance

Traefik will automatically request and renew the certificate when a matching route (host rule) is first accessed. The `tls.domains` configuration explicitly specifies that both the apex and wildcard must be on the same certificate:

```yaml
# In Traefik router/service config
- Host(`owt.craazzzyyfoxx.me`) || HostRegexp(`{subdomain:[a-zA-Z0-9-]+}.owt.craazzzyyfoxx.me`)
  tls:
    certResolver: dns-acme
    domains:
      - main: "owt.craazzzyyfoxx.me"
        sans:
          - "*.owt.craazzzyyfoxx.me"
```

**Important:** The `tls.domains` entry ensures that both the apex (`main`) and the wildcard (`sans`) are included on the certificate. Without explicit SAN configuration, Let's Encrypt may issue separate certificates.

**Note on HostRegexp (Traefik version):** Traefik v2 supports named captures in `HostRegexp` (e.g., `{subdomain:[a-zA-Z0-9-]+}`). Traefik v3 removed named-capture support from `HostRegexp` — use a plain regex pattern instead if upgrading to v3.

**Traefik will:**
1. Create a DNS TXT record in your domain via API (DNS-01 challenge)
2. Validate the record with Let's Encrypt
3. Issue the wildcard certificate
4. Store it in `./acme.json`

**Expected output in Traefik logs:**
```
[dns] acme: Using DNS provider (cloudflare)
[acme] Registering account...
[acme] Sending certificate request...
[acme] Cert obtained for *.owt.craazzzyyfoxx.me
```

#### Renewal

Traefik automatically renews certificates 30 days before expiry. Monitor Traefik logs to confirm renewals are working.

#### Manual Renewal (if needed)

In Traefik v2/v3, certificates are managed automatically by the `certificatesResolvers.<name>.acme` configuration and renew 30 days before expiry. If you need to force an immediate renewal:

1. **Locate the ACME storage file** (typically `/root/overwatch-tournaments/acme.json`):
   ```bash
   # On the host running Traefik
   ls -lh /root/overwatch-tournaments/acme.json
   ```

2. **Remove the stored certificate entry** (this forces re-issuance on next route access):
   ```bash
   # Backup first
   cp /root/overwatch-tournaments/acme.json /root/overwatch-tournaments/acme.json.backup
   
   # Remove the certificate entry (or delete the entire file to force re-issuance)
   rm /root/overwatch-tournaments/acme.json
   ```

3. **Restart Traefik** to trigger certificate re-issuance:
   ```bash
   # If Traefik runs as systemd service
   sudo systemctl restart traefik
   
   # Or if running in Docker
   docker restart traefik
   ```

4. **Monitor logs** to confirm the new certificate is issued:
   ```bash
   docker logs traefik | grep -i acme
   # or
   journalctl -u traefik -f
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

## 5. Custom Domains (Phase 2)

Custom domains let a workspace serve on a domain the *customer* owns and controls DNS for (e.g. `tourney.example.com`), instead of (or alongside) a `*.owt.craazzzyyfoxx.me` subdomain. Because we don't control the customer's DNS, this is a materially different ops story from Section 2's wildcard: verification is DNS-TXT-based ownership proof, and TLS is issued **on demand per domain via HTTP-01**, not the shared DNS-01 wildcard.

All record names, token formats, and gates below are quoted from the actual implementation — see the file:line references — not assumed.

### 5.1 What the code actually does (source of truth)

- **Verification token generation** — `backend/app-service/src/services/workspace/service.py:38,93`:
  ```python
  _CUSTOM_DOMAIN_TOKEN_PREFIX = "owt-verify-"
  ...
  token = _CUSTOM_DOMAIN_TOKEN_PREFIX + secrets.token_urlsafe(24)
  ```
  The stored token is always `owt-verify-<url-safe-random-string>` — copy it byte-for-byte from the admin UI; there is no way to recover/regenerate the same token without calling `set_custom_domain` again (which also resets `custom_domain_verified_at` to unverified).

- **DNS TXT record checked** — `verify_custom_domain`, `service.py:120-135`:
  ```python
  ok = await _dns_txt_contains(
      f"_owt-verify.{workspace.custom_domain}", workspace.custom_domain_verification_token
  )
  ```
  The record queried is **`_owt-verify.<custom_domain>`** (a dedicated subrecord under the customer's domain) — **not** a TXT on the apex of the customer's domain. `_dns_txt_contains` (`service.py:62-78`) does a live `dns.asyncresolver.resolve(name, "TXT")` lookup and fails closed (any DNS error → not verified, never a 500).

- **Domain normalization/guardrails** — `backend/shared/tenancy/hostnames.py:66-81` (`normalize_custom_domain`): lowercases, strips port/trailing dot, requires a valid multi-label FQDN, and explicitly rejects anything under the platform zone (`owt.craazzzyyfoxx.me` or a subdomain of it) — a customer cannot claim a domain that collides with Phase 1.

- **Resolver fail-closed** — `get_by_verified_custom_domain` (`backend/shared/repository/workspace.py:32-43`) only matches rows where `custom_domain_verified_at IS NOT NULL`. A domain that is set-but-unverified never resolves to a workspace, in `by_host`, in the gateway's WS origin check, or anywhere else.

### 5.2 Customer DNS records

Two records, two different purposes — give the customer **both**, but understand they gate different things:

| Record | Name | Value | Purpose |
|---|---|---|---|
| TXT | `_owt-verify.<custom-domain>` | The exact token shown in admin, e.g. `owt-verify-<random>` | **Ownership verification only.** Read once by "Verify"; not consulted again after `custom_domain_verified_at` is set. Can be removed after verification if the customer wants (re-verification, e.g. after `clear_custom_domain` + re-`set_custom_domain`, would need it added back). |
| CNAME (or A, if the domain is an apex and the registrar doesn't allow CNAME-at-apex) | `<custom-domain>` | `owt.craazzzyyfoxx.me` (CNAME) or the ingress IP (A record — same IP as Section 1's wildcard `A` record) | **Serving traffic + TLS issuance.** Must resolve to the ingress before Traefik's HTTP-01 challenge (Section 5.3) can succeed, and before real visitors reach the site. |

Both records are exactly what the admin UI (`frontend/src/app/admin/workspaces/page.tsx:729-753`) displays to the organiser once a custom domain is saved (unverified):

```
TXT   _owt-verify.tourney.example.com   owt-verify-<random-token>
CNAME tourney.example.com               owt.craazzzyyfoxx.me
```

Verification (Step 5.4 below) only needs the TXT record. Real traffic and TLS need the CNAME/A record. They can be added at the same time — there's no ordering requirement between them.

### 5.3 Traefik / TLS: on-demand HTTP-01 per custom domain

Section 2 already covers the wildcard `*.owt.craazzzyyfoxx.me` + apex certificate via **DNS-01** — that setup is unchanged and still the only cert covering the platform zone. Custom domains need a **separate, additional** certificate resolver because DNS-01 is not an option here: we do not have API credentials for a customer's DNS provider, and never will.

**Why HTTP-01 instead of DNS-01:** HTTP-01 only requires that the domain's DNS already resolves to our ingress (the CNAME/A record from Section 5.2) and that Traefik can answer an HTTP challenge request on that host at `/.well-known/acme-challenge/...`. No DNS API access is needed — it works for any domain pointed at us, regardless of registrar/provider.

**EXAMPLE Traefik dynamic config (file-provider style, matching the existing wildcard setup)** — adapt paths/entrypoint names to the actual host config:

```yaml
# EXAMPLE — add alongside the existing dns-acme resolver from Section 2,
# in the same Traefik file-provider directory.
certificatesResolvers:
  http-01:
    acme:
      email: admin@example.com
      storage: ./acme-http01.json   # separate storage file from the wildcard's acme.json
      httpChallenge:
        entryPoint: web             # the plain-HTTP (port 80) entrypoint

http:
  routers:
    custom-domains-catchall:
      # Broad catch-all: matches any host NOT already claimed by the named
      # apex/wildcard router from Section 2. Give the Section 2 router a
      # higher explicit `priority` (or rely on Traefik's longer-rule-wins
      # default, but an explicit priority is safer once both routers exist
      # in the same file) so `owt.craazzzyyfoxx.me` / `*.owt.craazzzyyfoxx.me`
      # traffic never falls into this catch-all.
      rule: "HostRegexp(`{domain:.+}`)"
      priority: 1
      entryPoints:
        - websecure
      service: gateway   # same backend service the Section 2 router points at
      tls:
        certResolver: http-01
```

**Let's Encrypt rate limits:** the "Certificates per Registered Domain" limit (currently 50/week, per LE's published limits — https://letsencrypt.org/docs/rate-limits/) is scoped to *the customer's own registered domain*, not to us — onboarding N customers does **not** share or exhaust a single aggregate budget across tenants the way the shared wildcard would. The one limit that *is* shared across all custom domains is the "New Orders per Account per 3 hours" cap (currently 300), since every HTTP-01 order goes through the same Traefik ACME account as the wildcard — fine at the expected scale (a handful to low dozens of custom domains), but worth knowing if custom-domain onboarding ever needs to happen in a burst.

### 5.4 Organiser steps (Admin UI)

1. Navigate to `/admin/workspaces` (gated: visible to `isSuperuser` or `isWorkspaceAdmin(workspace_id)` in the UI; **authoritatively enforced server-side** on every RPC by `ensure_workspace_permission(user, workspace_id, "workspace", "update")` — `backend/app-service/src/rpc/workspaces.py:347,367,383` — i.e. workspace owner/admin roles or a platform superuser).
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
   Note the frontend (`frontend/src/middleware.ts:6`) and this RPC both cache host→workspace lookups for up to 60 seconds (`CACHE_TTL_MS = 60_000`); allow up to a minute after verification before this check is guaranteed fresh.
5. **OAuth login round-trips.** From `https://tourney.example.com`, click Login. Confirm:
   - The browser is bounced to `https://owt.craazzzyyfoxx.me/auth/<provider>/login?origin=https://tourney.example.com&guard_hash=...` (`frontend/src/lib/oauth-login.ts`'s `onCustomDomain` branch) — a host-only `owt_xdomain_guard` cookie is set on `tourney.example.com` *before* this bounce, carrying no `domain` attribute.
   - After provider consent, the apex callback redirects back to `https://tourney.example.com/auth/sso?ticket=...&next=...`.
   - `frontend/src/app/(site)/auth/sso/route.ts` redeems the ticket (requires the `owt_xdomain_guard` cookie set in the first bullet — fails closed with `invalid_state` if missing), sets `owt_access_token`/`owt_refresh_token` **host-only** (no `domain` attribute — these are NOT the `.owt.craazzzyyfoxx.me`-scoped cookies from Phase 1) on `tourney.example.com`, and clears the guard cookie.
6. **Account linking works.** From an *already-logged-in* session on `tourney.example.com`, use the "Link account" flow; confirm `/auth/link/complete` redeems the link ticket against the live local session (it requires an existing session on that exact host — `getAccessToken`/`loginRedirect` in `frontend/src/app/(site)/auth/link/complete/route.ts` — and never establishes a new session from the ticket itself).
7. **WS connects.** Open DevTools → Network → WS while on `tourney.example.com`; confirm the WebSocket handshake succeeds. The gateway's dynamic origin check (`gateway/internal/ws/handler.go`, backed by `gateway/internal/workspace/workspace.go`'s `IsVerifiedCustomDomain`) queries `custom_domain = $1 AND custom_domain_verified_at IS NOT NULL` and caches the result (verified or not) for 60 seconds (`customDomainCacheTTL`) per origin host.
8. **Apex + subdomains unaffected.** Re-run the Section 4 checklist against `https://owt.craazzzyyfoxx.me` and an existing `*.owt.craazzzyyfoxx.me` workspace — both must still resolve, serve TLS, and connect WS exactly as before (regression check; Phase 2 additions are purely additive in the resolver and origin-allowlist code paths).
9. **Unknown/unverified host → 404 / no workspace.** Hit a domain that was never `set_custom_domain`'d, and (separately) a domain that is `set_custom_domain`'d but not yet verified. Both must fail closed: `by_host` returns `data: null`, no white-label chrome loads, and the WS handshake from that origin is rejected — never silently mapped to any workspace.

### 5.6 Rollback / Clear

- **Unset a custom domain entirely:** `clear_custom_domain` (`DELETE /api/v1/workspaces/{workspace_id}/custom-domain`) wipes `custom_domain`, `custom_domain_verification_token`, and `custom_domain_verified_at` together. In the admin UI, the **Remove** button only appears once the domain is *verified*. For a domain that is still pending (saved but not yet verified), the UI's only exposed action is overwriting it via **Save** with a new value (which mints a fresh token and keeps the workspace unverified) — there's no dedicated "cancel" button for a pending, not-yet-verified domain. To fully clear a pending domain without replacing it, call the same endpoint directly: `DELETE /api/v1/workspaces/{workspace_id}/custom-domain` with a bearer token that has `workspace.update` for that workspace.
- **Propagation delay after any change:** both the gateway's WS-origin cache (`customDomainCacheTTL = 60 * time.Second`, `gateway/internal/workspace/workspace.go:35`) and the frontend's `by_host` middleware cache (`CACHE_TTL_MS = 60_000`, `frontend/src/middleware.ts:6`) mean a `set_custom_domain`, `verify_custom_domain`, or `clear_custom_domain` change can take **up to ~60 seconds** to take full effect for WS connections and page routing, even though the admin UI reflects the change immediately (it re-fetches the workspace directly, bypassing both caches).
- **Re-verifying after `clear_custom_domain` + re-`set_custom_domain`:** the token is regenerated every time `set_custom_domain` runs, so the customer must re-add the TXT record with the *new* token value — the old TXT value will no longer match.

---

## Rollback / Troubleshooting

### DNS Propagation Delay
If DNS changes don't resolve immediately:
- Wait 5–10 minutes for TTL expiry
- Flush local DNS cache: `ipconfig /flushdns` (Windows) or `sudo dscacheutil -flushcache` (macOS)
- Use `dig` or `nslookup` with a public resolver: `nslookup owt.craazzzyyfoxx.me 8.8.8.8`

### TLS Certificate Errors
- Check Traefik logs: `docker logs traefik` or `journalctl -u traefik` (systemd)
- Ensure DNS provider credentials are set and correct
- Clear `acme.json` and restart Traefik to force a re-issue (caution: rate limits may apply)

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

- **Traefik ACME & DNS-01:** https://doc.traefik.io/traefik/https/acme/
- **Traefik ACME & HTTP-01** (Section 5): https://doc.traefik.io/traefik/https/acme/#httpchallenge
- **Let's Encrypt Rate Limits:** https://letsencrypt.org/docs/rate-limits/
- **OAuth 2.0 Redirect URI Security:** https://oauth.net/2/redirect-uris/
- **Custom-domain source of truth:** `backend/app-service/src/services/workspace/service.py` (`set_custom_domain`, `verify_custom_domain`, `_dns_txt_contains`), `backend/app-service/src/rpc/workspaces.py` (RPC gates), `backend/shared/tenancy/hostnames.py` (`normalize_custom_domain`), `gateway/internal/workspace/workspace.go` (`IsVerifiedCustomDomain`), `gateway/internal/ws/handler.go` (dynamic WS origin check), `frontend/src/app/admin/workspaces/page.tsx` (organiser UI), `frontend/src/lib/oauth-login.ts` / `frontend/src/app/(site)/auth/sso/route.ts` / `frontend/src/app/(site)/auth/link/complete/route.ts` (OAuth apex-bounce + ticket handoff)
