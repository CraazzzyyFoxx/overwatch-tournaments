# Workspace Subdomains: Ops Runbook

**Date:** 2026-07-06  
**Platform Zone:** `owt.craazzzyyfoxx.me`  
**Phase:** 1 (subdomains, single OAuth callback)

This document describes the out-of-repo operational steps required to enable workspace multi-domain support via subdomains.

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
- **Let's Encrypt Rate Limits:** https://letsencrypt.org/docs/rate-limits/
- **OAuth 2.0 Redirect URI Security:** https://oauth.net/2/redirect-uris/
