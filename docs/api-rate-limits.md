# API rate limits and quotas

What an API client is allowed to spend, how a refusal looks, and how to read your own remaining
budget. This is the client-facing contract; the design behind it is
[`docs/plans/2026-09-17-api-key-rate-limits.md`](./plans/2026-09-17-api-key-rate-limits.md), and the
enforcement code is `backend/shared/quota/`.

**Related documents**

- System overview: [`docs/architecture.md`](./architecture.md)
- API keys, scopes and the identity they carry: [`docs/users-identity.md`](./users-identity.md)
- Backend layering and the error envelope: [`backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md)

---

## 1. What is metered

Reads are not metered. Writes and compute are: every operation that spends CPU, storage or a
third-party API quota calls the shared gate before it starts, and the gate either lets it through or
refuses it.

Each metered call spends **two** things:

1. **One request token**, always, against `requests_per_minute`.
2. **The operation's cost** in *heavy units*, against `heavy_per_day` — but only if the operation is
   priced. An operation with no row in the catalogue (§5) costs nothing beyond its request token.

Long-running work (a balancer job, a multi-minute solve) additionally holds a **concurrency slot**
for as long as it runs, and releases it when it finishes. A worker that dies mid-job does not hold
its slot forever: the slot carries its own expiry and the next reservation reclaims it.

## 2. Two scopes, and the tighter one refuses

Every metered call is checked against two budgets at once.

| Scope | Shared by | Answers |
|---|---|---|
| `workspace` | every API key **and** every member's interactive session in that workspace | how much this tenant may consume in total |
| `key` / `session` | one API key, or one signed-in user | how much a single client may consume of it |

`key` applies to an API-key credential, `session` to an interactive user; they are the same
"per-principal" scope under two names, so a machine client and a human can carry different ceilings
while sharing one tenant budget.

Both are evaluated before anything is spent, and the check is **all-or-nothing**: if either scope
would be exceeded, nothing is counted at all. A client in a retry loop therefore cannot drain the
tenant budget with requests that were refused anyway. The refusal names which scope hit its ceiling
(`details.scope`), which is how you tell "my key is throttled" from "my workspace is out of budget".

A scope with no value set for a dimension is unlimited in that dimension. A workspace-only
configuration is legitimate, and so is a key-only one — which is what the shipped defaults are (§4).

## 3. The five dimensions

| Dimension | Unit | Kind | Window |
|---|---|---|---|
| `requests_per_minute` | metered calls | counter | rolling 60 s |
| `heavy_per_day` | heavy units (the operation's cost) | counter | UTC calendar day |
| `concurrent_heavy` | simultaneously running heavy jobs | live count | held for the job's lifetime |
| `max_upload_bytes` | bytes in one request body | per-request cap | — |
| `max_items_per_request` | items in one request (players, rules, rows) | per-request cap | — |

The two kinds behave differently on purpose:

- **Counters** take the *most specific* value that is set — a per-key override wins over the
  workspace override, which wins over the plan — so a budget can be raised for one client.
- **Per-request caps** take the *minimum* of every level that sets one, so a tenant can tighten what
  its own keys may upload without anyone raising a limit for them.

The day boundary is UTC for every tenant, regardless of the workspace's timezone.

## 4. What a plan allows

A workspace runs on a **plan**. By default the plan is the one named after the workspace's
verification status (`unverified`, `verified`, `trusted`); a workspace may also be pointed at a named
plan explicitly, in which case its verification status no longer selects the plan. A principal acting
outside any workspace resolves the plan `default`.

These are the values seeded by
[`backend/migrations/versions/quota0001_quota_schema.py`](../backend/migrations/versions/quota0001_quota_schema.py)
(lines 159-184). All four plans ship **identical** limits: the seed reproduces the hardcoded numbers
that were already in force before quotas became configurable, so nothing changed the day it landed.
Differentiating the tiers is an operator decision taken against live numbers.

| Plan | Scope | `requests_per_minute` | `heavy_per_day` | `concurrent_heavy` | `max_upload_bytes` | `max_items_per_request` |
|---|---|---|---|---|---|---|
| `unverified`, `verified`, `trusted`, `default` | `workspace` | unlimited | unlimited | unlimited | unlimited | unlimited |
| `unverified`, `verified`, `trusted`, `default` | `key` | 60 | 100 | 2 | 10485760 (10 MiB) | 500 |
| `unverified`, `verified`, `trusted`, `default` | `session` | 120 | 500 | 3 | 26214400 (25 MiB) | 1000 |

No `workspace`-scope rows are seeded: the tenant-wide pool starts unlimited, because tightening a
shared budget below what a tenant's keys already spend is a deliberate, per-tenant decision. Your
workspace may have one configured — read it back rather than assuming (§8).

An operator can override any of these per workspace or per key; §10.

## 5. What an operation costs

Costs are relative to `1` = "one ordinary balancer job", and they are data, not code: re-pricing an
operation is a configuration change. `balancer.job` is seeded by
[`quota0001_quota_schema.py`](../backend/migrations/versions/quota0001_quota_schema.py) (lines
185-189); everything else by
[`quota0002_metered_operations.py`](../backend/migrations/versions/quota0002_metered_operations.py)
(lines 34-56).

| Operation | Cost | What it does |
|---|---|---|
| `balancer.job` | 1 | Runs a balancing solve (queued or inline) |
| `balancer.balance_export` | 3 | Materializes a balance into tournament teams, players and standings |
| `balancer.balance_ranks_export` | 3 | Rewrites tournament player ranks from a saved balance |
| `balancer.teams_import` | 2 | Imports a multi-MB team payload and rewrites the roster |
| `balancer.teams_export` | 2 | Materializes every complete registered team |
| `parser.logs.upload` | 1 | Stores an uploaded match log and queues its parse |
| `parser.logs.process_tournament` | 5 | Re-parses every log of one tournament |
| `parser.ach.import` | 5 | Imports portable achievement rules |
| `parser.ach.export` | 2 | Exports achievement rules |
| `parser.ach.lib_import` | 5 | Imports the achievement library |
| `parser.ach.calculate` | 3 | Recomputes achievements for a workspace |
| `parser.ach.calculate_tournament` | 2 | Recomputes achievements for one tournament |
| `tournament.challonge_import` | 5 | Imports a bracket from Challonge |
| `tournament.challonge_export` | 5 | Pushes a bracket to Challonge |
| `tournament.sheet_sync` | 3 | Syncs a registration Google Sheet |
| `tournament.sheet_players_export` | 2 | Exports registered players to a Google Sheet |
| `analytics.train` | 10 | Trains the analytics models — the most expensive call in the platform |
| `analytics.infer` | 5 | Runs inference over a tournament |
| `analytics.recalculate` | 5 | Recomputes analytics for a tournament |
| `app.assets.upload` | 1 | Stores a workspace asset |
| `app.workspace_icon_upload` | 1 | Stores a workspace icon |
| `stream.repoll` | 3 | Re-polls every live tournament against the shared Twitch Helix budget |

On the seeded 100 heavy units per key per day (§4) that is roughly 100 balancer jobs, or 20 Challonge
imports, or 10 model trainings — and any mix of them draws on the same pool.

An operation can also be disabled outright, in which case every call to it is refused regardless of
budget. Metered operations that do not appear above cost one request token and nothing else.

## 6. When you are refused

Every refusal arrives as the standard error envelope — `{"ok": false, "error": {...}}` over RPC,
mapped to an HTTP status by the gateway. Two codes travel in it and they are not the same thing:

- **`error.code`** is derived from the HTTP status (`rate_limited`, `payload_too_large`,
  `bad_request`, `unavailable`). The gateway writes it last and deliberately lets it win, so a
  worker can never rewrite the key every client branches on.
- **`error.details.fields[0].code`** is the specific quota reason, and it carries the attributes of
  the refusal alongside it: `limit_name`, `scope`, `limit`.

| HTTP | `error.code` | `details.fields[0].code` | Meaning |
|---|---|---|---|
| 429 | `rate_limited` | `quota_exceeded` | `requests_per_minute`, `heavy_per_day` or `concurrent_heavy` is exhausted. Also `details.retry_after` and a `Retry-After` header |
| 413 | `payload_too_large` | `quota_payload_too_large` | the request body exceeds `max_upload_bytes` |
| 400 | `bad_request` | `quota_items_too_many` | the request carries more items than `max_items_per_request` |
| 503 | `unavailable` | `quota_unavailable` | the accounting store is unreachable and this operation deliberately fails closed rather than running unmetered. Also `Retry-After: 30` |

Every one of those `fields[0]` entries carries `limit_name`, `scope` and `limit` — except
`quota_unavailable`, which carries the `operation` that could not be accounted.

```json
{
  "ok": false,
  "error": {
    "code": "rate_limited",
    "message": "quota exceeded",
    "details": {
      "retry_after": 41231,
      "fields": [
        {
          "field": null,
          "msg": "quota exceeded",
          "code": "quota_exceeded",
          "limit_name": "heavy_per_day",
          "scope": "key",
          "limit": 100
        }
      ]
    }
  }
}
```

That is the `/api/v2` body, which is the RPC envelope verbatim. On `/api/v1` the same refusal is
flattened — every `details` key is lifted to the top of the body, next to `detail` and `code`:

```json
{
  "fields": [
    {
      "field": null,
      "msg": "quota exceeded",
      "code": "quota_exceeded",
      "limit_name": "heavy_per_day",
      "scope": "key",
      "limit": 100
    }
  ],
  "retry_after": 41231,
  "detail": "quota exceeded",
  "code": "rate_limited"
}
```

So the reason is `fields[0].code` on v1 and `error.details.fields[0].code` on v2. `detail`/`code`
are written last on v1 and cannot be shadowed by a worker.

Either shape, the field that matters is **`scope`**: it tells you whose budget ran out.
`scope: "key"` means this credential is throttled while the rest of the workspace keeps working —
use a different key, or ask for a raise on this one. `scope: "workspace"` means the tenant as a
whole is out and every client in it will be refused until the window rolls.

`Retry-After` is the honest wait in seconds: until the end of the 60 s window for
`requests_per_minute`, until UTC midnight for `heavy_per_day`, and a flat 30 s for a concurrency
refusal (which has no window — it clears when a running job finishes).

Two behaviours worth relying on:

- **A refusal costs nothing.** Nothing is counted when a call is refused, at either scope.
- **A failed heavy job is not refunded.** `heavy_per_day` is charged when the job is admitted, not
  when it succeeds: a failed expensive job consumed the same CPU as a successful one.

The 429 is also what the edge returns when the gateway's own per-key bucket refuses first — same
`code`, same body shape — so branch on `rate_limited` rather than on which layer answered.

## 7. Rate-limit headers

For API-key traffic the gateway reports the per-minute request bucket on **every** response, success
or refusal:

| Header | Meaning |
|---|---|
| `RateLimit-Limit` | requests allowed in the 60-second window |
| `RateLimit-Remaining` | requests left in the current window, floored at 0 |
| `RateLimit-Reset` | seconds until the window resets |
| `Retry-After` | on a 429 only: seconds to wait before retrying |

These cover `requests_per_minute` at the edge only. `heavy_per_day` and `concurrent_heavy` are not
visible in headers — read them from the usage endpoint below.

Interactive sessions and anonymous traffic get no `RateLimit-*` headers.

## 8. Reading your own budget

A key can read its own limits and consumption without any extra grant:
`rpc.identity.api_key.self_quota`, authenticated by the key itself (a session bearer is refused with
403). An administrator can read the same for any key in a workspace they manage with
`rpc.identity.api_key.quota_usage`, passing `{"api_key_id": <id>}` — the workspace is taken from the
key, never from the request. Both return the same shape
(`backend/shared/schemas/quota.py:QuotaUsageRead`) — below, a workspace whose operator has
configured a tenant budget rather than the unlimited default:

```json
{
  "plan_slug": "verified",
  "workspace_id": 42,
  "scopes": [
    {
      "scope": "workspace",
      "requests_per_minute": null, "requests_used": 0,   "requests_reset_in": null,
      "heavy_per_day": 2000,       "heavy_used": 180,    "heavy_reset_in": 41231,
      "concurrent_heavy": 4,       "concurrent_used": 1,
      "max_upload_bytes": null,    "max_items_per_request": null
    },
    {
      "scope": "key",
      "requests_per_minute": 60,   "requests_used": 12,  "requests_reset_in": 48,
      "heavy_per_day": 100,        "heavy_used": 100,    "heavy_reset_in": 41231,
      "concurrent_heavy": 2,       "concurrent_used": 1,
      "max_upload_bytes": 10485760, "max_items_per_request": 500
    }
  ]
}
```

`null` in a limit field means unlimited in that dimension at that scope. `*_used` is the current
counter, `*_reset_in` the seconds until it rolls. The `scopes` list carries the workspace entry first
and the principal entry (`key` or `session`) second — which is exactly the pair of bars to render, and
the cheapest way to answer "is it me or is it us?" before opening a support ticket.

Both are RPC subjects: no HTTP route is exposed at the edge for them yet. They are declared in
identity-service's `OPERATIONS`/`DOCS` tables, so they appear in the generated reference at
`/api/docs` as soon as a gateway route lands.

## 9. What is not metered

- **Anonymous public reads.** Tournament pages, standings and other unauthenticated `GET`s spend no
  quota. They are bounded at the edge instead: nginx allows 40 r/s per client IP across the whole API
  with a burst of 120, 10 r/m on the upload endpoints, and 100 concurrent in-flight requests per IP
  (`nginx/nginx.conf`, the `req_edge` / `req_upload` / `conn_edge` zones). The gateway additionally
  has a per-IP anonymous bucket, disabled by default (`GATEWAY_ANON_RATE_LIMIT`,
  `gateway/internal/config/config.go`).
- **Authenticated reads** that do not call the gate — listing tournaments, polling a job's status —
  cost nothing beyond the edge limits above.
- **Login and token refresh**, bounded separately at 10 requests per 60 s per IP
  (`GATEWAY_AUTH_RATE_LIMIT`) and by nginx's `req_auth` zone.
- **Outbound third-party budgets** (Twitch Helix, Challonge, Google Sheets) are the platform's own
  concern; they can make a call fail for reasons unrelated to your quota.

## 10. Asking for more

A **superuser** can raise or lower anything: re-price an operation, edit a plan's limits, point one
workspace at a dedicated plan without touching its verification status, or write a per-key override
that exceeds what the key would otherwise inherit. That last one is the usual answer for a single
bulk-import integration that needs more than its tenant's plan allows.

A **workspace administrator** (`team.create` in the workspace) can only ever *lower* a limit — for the
workspace as a whole or for one of its keys. An attempt to set a value above what it would inherit is
rejected at write time with a 422 whose `details.fields[0]` reads
`{code: "quota_above_inherited", limit_name, limit, requested}`; nothing is clamped silently at
read time, so the stored number is always the effective one. Clearing every field of an override
deletes it and restores inheritance. Both kinds of write are audited (`workspace.quota_update`,
`api_key.quota_update`).

Practically: ask your workspace administrator first if the answer is "lower something else", and ask
the platform operators for anything that raises a ceiling.

**For an operator changing these numbers:**

| What | Where |
|---|---|
| Seeded plans and their limits | [`backend/migrations/versions/quota0001_quota_schema.py`](../backend/migrations/versions/quota0001_quota_schema.py) |
| Operation prices | [`backend/migrations/versions/quota0002_metered_operations.py`](../backend/migrations/versions/quota0002_metered_operations.py) |
| Live edits (plans, prices, per-workspace and per-key overrides) | the admin surface over the `quota` schema — `rpc.quota.plan.*`, `rpc.quota.operation.*`, `rpc.app.workspaces.quota_set`, `rpc.identity.api_key.quota_set` |
| Disable one operation | set its `enabled = false` in `quota.operation`; it takes effect without a deploy |
| Disable the whole gate | `QUOTA_ENABLED=false` (restart-scoped; [`backend/shared/core/config.py`](../backend/shared/core/config.py)) |
| Enforcement itself | [`backend/shared/quota/`](../backend/shared/quota/) |
| Edge per-key bucket | `GATEWAY_API_KEY_RATE_LIMIT` (default 60/min for a key with no `requests_per_minute` of its own), `gateway/internal/config/config.go` |
