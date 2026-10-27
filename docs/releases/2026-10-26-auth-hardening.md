# Auth hardening: EdDSA tokens, a credentials process, sealed provider tokens: release note

Access and service tokens are now Ed25519 (EdDSA) JWTs. identity derives the signing key from `JWT_SECRET_KEY`, and
the gateway verifies tokens with the public half only, so it can no longer mint them and no longer reads `auth.env`.
Production runs identity as two processes from one image. Discord and Twitch tokens are encrypted at rest. The deploy
needs new keys in the untracked env files **before** `make prod-up`: without them the gateway and identity refuse to
start.

## Behaviour changes

- **Token format.** An access token carries only `sub`, `sid`, `type="access"`, `iat`, `exp`,
  `iss="owt-identity"`, `aud="owt"` and a random `jti`. Email, username and `is_superuser` are gone; RBAC still comes
  from `rpc.identity.validate_token`. Service tokens gain `iat` and `jti`. The gateway accepts EdDSA only, so a token
  minted by the previous release fails there and the client refreshes. identity itself still accepts those HS256
  tokens for one access-token lifetime (15 min by default) after it starts.
- **WebSocket auth.** `?token=` is gone: browsers authenticate with the session cookie, scripts with
  `Authorization: Bearer`.
- **Credential checks.** 10 failed sign-ins for one email within 15 minutes answer 429 until 15 minutes after the
  first failure; a successful sign-in clears the count. Deleting an account needs the current password, or a sign-in
  no older than 10 minutes for an account without one (else 403 `reauth_required`). The same recency rule applies to
  setting a first password. Changing a password signs out every other session.
- **Provider tokens.** Discord and Twitch access/refresh tokens are stored AES-GCM-sealed. Battle.net and Riot tokens
  are no longer stored. On startup, identity (core role) seals the existing rows and clears the Battle.net and Riot
  ones.
- **RBAC cache.** The entry TTL is 600 s (was 60 s) under the new prefix `rbac:v4:user:`, and the entry now also holds
  the account's email, username, `is_active` and `is_superuser`, so a cache hit validates a token with no database
  read. Every identity core process flushes the whole cache at startup, because membership-change events may have
  expired while it was down. A manual SQL change to those account columns (e.g. re-activating an account) is
  invisible for up to 10 minutes unless the user's entry is dropped (restart identity-svc, or
  `rpc.identity.invalidate_session` with the `identity:invalidate` scope).
- **`rpc.identity.invalidate_session`** requires the service-token scope `identity:invalidate` (403 without it).
- **Two identity processes.** `identity-svc` runs with `IDENTITY_RPC_ROLE=core` (validate_token, RBAC, API keys,
  players, avatars, event consumers, schedulers). The new `identity-auth-svc` runs with `IDENTITY_RPC_ROLE=credentials`:
  sign-in, refresh, sessions, account and OAuth. It has the same image and limits, metrics on 9112 and logs in
  `logs/identity-auth-svc`. A login burst no longer queues the gateway's token checks. The dev compose file keeps
  one `all` process.

## Configuration

Set these on every environment: production, the dev site and every local checkout.

| File | Variable | Default | Effect |
| --- | --- | --- | --- |
| `gateway.env` | `JWT_PUBLIC_KEY` | none, required | identity's Ed25519 public key, base64url without padding (43 chars). Derived from `JWT_SECRET_KEY`: recompute it whenever that changes. |
| `auth.env`, `stats.env`, `tournament.env` | `OAUTH_TOKEN_ENCRYPTION_KEY` | unset | base64url of 32 random bytes, **the same value in all three**. identity refuses to start without it while Discord or Twitch OAuth is enabled; stats and tournament log an error and resolve Twitch checks `unknown`. |
| `auth.env` | `JWT_ALGORITHM` | removed | Ignored; delete the line. |
| `auth.env` | `SERVICE_SCOPES` | `{}` | Add `identity:invalidate` for every external client that calls `rpc.identity.invalidate_session`. No in-repo service does. |
| `identity.env` | `IDENTITY_RPC_ROLE` | `all` | Leave it unset. Production compose sets it per service, and dev runs `all`. |

Generate the encryption key **once** per environment and never rotate it casually. Rows sealed with the old key stop
opening, and their users have to re-link Discord and Twitch:

```bash
python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"
```

Local checkouts: `make jwt-public-key` runs inside the dev identity image, so rebuild it first
(`docker compose build identity-svc`) if the image predates this release (an older image has no PyJWT). Running
stacks, the e2e one included, need their images rebuilt and the new keys before they pick any of this up.

## Migration and deploy

One migration after `authavatar01`: **`rtexp01`** indexes `auth.refresh_token(expires_at)` for the daily purge
(plain `CREATE INDEX`; ~90k narrow rows, well under a second). `authavatar01` comes from
[the identity write-ownership release](./2026-10-26-identity-write-ownership.md): the two ship together.

1. **Prefetch the release images** (deploy run with `DEPLOY_FREEZE=true`). Then compute the gateway key on the host
   from the release's identity image, with the host's own `auth.env`:

   ```bash
   IMAGE_TAG=<release> docker compose -f docker-compose.production.yml run --rm --no-deps -T identity-svc \
       python -c "from src.services.security import token_codec; print(token_codec.public_key_b64)"
   ```

   This is what `make prod-jwt-public-key` runs from this release on; the checkout still on the old release does not
   have that target yet. Put the output into `JWT_PUBLIC_KEY` in `backend/env/gateway.env`.
2. **Edit the env files** per the table: `OAUTH_TOKEN_ENCRYPTION_KEY` in `auth.env`, `stats.env` and
   `tournament.env`; drop `JWT_ALGORITHM`; grant `identity:invalidate` to external callers.
3. **Deploy** (`DEPLOY_FREEZE` unset). `remote-deploy.sh` runs the migrations first while the old stack serves, then
   `make prod-up` starts `identity-auth-svc` and recreates `identity-svc`, the gateway (it now waits for both identity
   processes), stats and tournament (their env changed) together. Expect about a minute of 401s, each recovered by
   the client's refresh, and every WebSocket reconnects once.
4. **Monitoring.** `make prod-up` recreates Alloy onto the new `moscow.alloy` (`ALLOY_CONF_SHA`), which adds the
   `identity-auth-svc:9112` scrape. If Alloy is not running under `make prod-up`, restart it
   (`docker compose -f docker-compose.production.yml --profile telemetry up -d alloy`). Prometheus on home receives
   remote writes and needs no change.
5. **After a day live**, remove the transitional HS256 branch in `identity-service/src/services/security.py`
   (`TokenCodec.decode`, marked `ponytail:`) in the next release.

## Rollback

Restore the old checkout and images. The old compose file gives the gateway `auth.env` back. The new env keys are
ignored by the old code, and the `rtexp01` index is harmless to it. EdDSA tokens fail at the old gateway and clients
refresh into HS256 ones. Discord and Twitch tokens already sealed are unreadable to the old code: those features fail
for the affected users until they re-link, so roll back only for a reason that outweighs that.
