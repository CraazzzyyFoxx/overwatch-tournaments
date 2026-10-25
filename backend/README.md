# Backend

The OWT backend is a Python 3.14 monorepo of **headless [FastStream](https://faststream.ag2.ai/)
workers**. Each service is a long-running RabbitMQ RPC worker (not an HTTP server) that shares one
ORM/schema layer through [`shared/`](./shared/README.md). The **only** HTTP/WebSocket entry point is
the Go [`gateway/`](../gateway/README.md), which terminates HTTP, validates JWTs, and translates REST
routes into typed request/reply RPC over RabbitMQ (`rpc.<service>.<method>`) to these workers.

For the end-to-end request flow, edge topology, and data model see the system overview in
[`../docs/architecture.md`](../docs/architecture.md). For what goes where **inside** one
service's `src/` — the rpc/services/domain/repository/models layers and the rules for each —
see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

Dependencies are managed as a single [uv](https://docs.astral.sh/uv/) workspace rooted at this
directory; each service still keeps its own `pyproject.toml` as a workspace member.

## Services

| Service dir | Compose service | Kind | Purpose |
| --- | --- | --- | --- |
| [`app-service`](./app-service/README.md) | `app-svc` | RPC worker | Game catalog, player identity (directory/search, admin, merge), workspaces, notifications, audit, binary assets |
| [`identity-service`](./identity-service/README.md) | `identity-svc` | RPC worker | AuthN/AuthZ: JWT, Discord OAuth, RBAC, workspace membership, custom domains/subdomains, API keys, player linking, service tokens, SSO |
| [`tournament-service`](./tournament-service/README.md) | `tournament-svc` | RPC + scheduler | Tournament lifecycle: CRUD, registration, brackets/standings, Challonge + Google Sheets sync, map veto, state machine, the organizer dashboard and tournament readiness; drains its own outbox rows (as every producing service does) |
| [`stats-service`](./stats-service/README.md) | `stats-svc` + `stats-worker` | RPC process + worker | Match-log ingestion/parsing, rank fetch (leader-locked), achievement evaluation, MVP-impact backfill; the public statistics, `/users/*` player-statistics and achievement reads with their read caches |
| [`balancer-service`](./balancer-service/README.md) | `balancer-svc` | RPC worker | Genetic team balancing + live draft; heavy solve in native Rust `tournament_balancer` (NSGA multi-objective) |
| [`analytics-service`](./analytics-service/README.md) | `analytics-svc` + `analytics-worker` | RPC worker + compute worker | Post-tournament analytics, split into two processes: `analytics-svc` (light RPC reads/mutations/job-control) and `analytics-worker` (heavy ML: LightGBM/XGBoost + Bayesian + Monte Carlo) |
| [`stream-service`](./stream-service/README.md) | `stream-svc` | RPC + scheduler | Tournament stream live-status: Twitch Helix `GET /streams` poll tick under an app token (leader-locked, admin-settings-gated) + public `rpc.stream.*` reads. Live state lives in Redis under a TTL; the participants' observed POV broadcasts and their Twitch VOD ids live in the `stream` schema, read back as per-VOD match timestamps |
| [`discord-service`](./discord-service/README.md) | `discord-worker` | Bot | discord.py bot: watches tournament channels, uploads match-log attachments to stats-service over RabbitMQ, delivers notifications, FastStream consumer |
| [`shared`](./shared/README.md) | — | Library | Single-source ORM + cross-service kernel; not a running service |

All workers start with `faststream run serve:app` (analytics has both `serve_rpc:app` and `serve:app`;
discord runs `python main.py`). The only ports they expose are Prometheus `WORKER_METRICS_PORT`s —
they are **not** HTTP APIs. HTTP is served exclusively by the gateway (`:8080`).

## Requirements

* [Docker](https://www.docker.com/) and Docker Compose.
* [uv](https://docs.astral.sh/uv/) for Python package and environment management (Python 3.14, pinned by `backend/.python-version`).

## General workflow

Dependencies are managed as a uv workspace. From `./backend/` install everything with:

```console
$ uv sync
```

Then activate the virtual environment:

```console
$ source .venv/bin/activate        # Linux/macOS
$ .venv\Scripts\activate           # Windows
```

Make sure your editor uses the workspace interpreter at `backend/.venv/bin/python`.

Shared SQLAlchemy models live in [`shared/models/`](./shared/README.md) (the single source of truth).
Service-specific business logic lives under each service's `src/`.

## Docker Compose (dev profiles)

Development behavior lives directly in the repository-root `docker-compose.yml`:

- source folders are bind-mounted for live reload (`--reload`),
- local PostgreSQL, Redis, and RabbitMQ are included by default,
- the gateway and nginx are part of the default stack,
- optional components (`analytics-worker`, `discord-worker`) live behind the `workers` profile.

### Start core dev stack

```console
$ docker compose up -d --wait
```

(Equivalent to `make dev-up`. The gateway and nginx come up by default — there is **no**
`--profile gateway`.)

### Start full dev stack (core + workers)

```console
$ docker compose --profile workers up -d --wait
```

(Equivalent to `make dev-up-full`.)

### Enter a running service container

```console
$ docker compose exec app-svc bash
```

### Environment files

Each service loads `backend/env/common.env` plus its own `backend/env/<service>.env`. Copy the
`*.env.example` templates to matching `.env` files before first start.

## Tests

Run the backend test suite (pytest, executed inside `app-svc`):

```console
$ make test
```

The lower-level `bash ./scripts/test.sh` still exists, but prefer `make test`. A coverage report is
generated at `htmlcov/index.html`.

## Migrations

Database schema is managed with [Alembic](https://alembic.sqlalchemy.org/); migration scripts live in
[`backend/migrations/`](./migrations) and target the shared models in [`shared/models/`](./shared/README.md).

* Apply migrations (`alembic upgrade head` inside `app-svc`):

```console
$ make migrate
```

* For interactive Alembic work, open a shell in `app-svc` (there is no `backend` compose service):

```console
$ docker compose exec app-svc bash
```

* After changing a model (for example, adding a column), create a revision:

```console
$ alembic revision --autogenerate -m "Add column last_name to User model"
```

* Commit the generated files in the `migrations/` directory, then apply with `make migrate`.

### P4 statistics cutover (`stats01` → `stats01a`)

This is a maintenance cutover, not an online migration. Drain writers before preparation,
upgrade and initial receipt capture. Fresh `stats01` preserves historical observations with
an independent encounter owner and an optional proven game binding; `stats01a` upgrades the
original bound-only schema after a full source/native proof. Unexplained prior mutations fail closed.
Missing raw bytes and uncertain historical order are represented explicitly, not repaired by
inventing hashes or games. Unsafe keys, foreign owners, invalid facts and missing members still block.

The migration copies at most 100 matches per statement inside one transaction, moves Discord
channels, repoints alias/achievement references, rewrites stored dependencies, refreshes the native
MV and reconciles the full transfer. Failed upgrades roll back. Reversing a committed cutover
requires a restore-proven backup, not an Alembic downgrade.
Participation preflight groups source identities once without sampling facts. Native seat multiplicity,
including replaced seats, remains authoritative: neither a missing nor an ambiguous owner is guessed.
During the locked migration, distinct endpoint identities and their handles are indexed once;
each 100-match copy reuses those lookups rather than rereading the full statistics stream.
Fact projection casts the small legacy-name lookup to the source enum, not every source fact
to text; this preserves PostgreSQL's source-column cardinality information for bulk-copy plans.
The bulk-loaded native match/fact/vocabulary tables are explicitly analyzed before the first
aggregate refresh; autovacuum cannot supply their column statistics inside the cutover transaction.

The earlier encounter-layer transfer also preserves incomplete history: disputed role/rank becomes
unknown, unresolved roster sides remain unasserted, and original registrations are retained in
`encounter.history_unresolved` audits. A self-duel retains both result positions but not a fictional
second source team. Replay codes without a proven game remain in their captain report's
`custom_fields_json.historical_replay_codes`; the source-drop gate verifies every original claim.

The role transfer treats `flex` as an open-role marker, not a second concrete role.
A known damage/support/tank assignment is retained alongside that marker; original text-role
rows remain available for reconciliation. Two genuine concrete roles still fail preflight.

For a large fresh dump, commit the catalog checkpoint with `alembic upgrade discipline01`
before continuing to `discipline01c`, then `stats01a`; a later preflight refusal must not
roll back the expensive catalog remap. Any extended statement deadline belongs only to
the migration connection, never to production-wide role/database defaults.


With writers still drained, publish the immutable receipt:

```console
uv run python scripts/stats01_reconcile.py --mode capture --receipt-dir p4-receipt --report p4-initial.json
```

Keep all three immutable receipt files together: `manifest.json`, `owners.jsonl` and
`handles.jsonl`. Format `stats01-receipt/2` freezes handles per match/player/team,
with streamed row counts and digests; later checks never reconstruct historical handles
from renamed current rosters or social profiles. Incomplete receipts are refused. Original codec1
receipts remain supported as immutable `--prior-receipt-dir` inputs; their original proof is not repinned.
Codec2 match-owner metadata also requires nullable `historical_reference_id`, frozen from the
independent source mapping. Later deletions cannot renumber surviving provenance; incomplete
experimental codec2 evidence is refused. Report paths cannot overwrite either the new receipt
or a `--prior-receipt-dir` input, including filesystem aliases.
Receipt snapshots use a dedicated physical PostgreSQL session for committed temporary projections
and one repeatable-read, read-only transaction; repeated checks do not reuse pooled temporary state.
The full summary materializes only the set of mismatching class names once, rather than
expanding the complete comparison view for every class. Every source/native row is still checked.
Initial capture indexes the small identity/handle lookups used by the migration. Their temporary
schemas are prepared first, but rows are loaded and analyzed only inside that same read-only
snapshot; facts and events are never materialized or sampled.

Later, validate current data and the actual native mutation audit chains:

```console
uv run python scripts/stats01_reconcile.py --mode check --receipt-dir p4-receipt --audit-source database --export-audit p4-lifecycle-audit.jsonl --report p4-current.json
```

Exit codes: `0` unchanged, `2` valid changes requiring release review, `1` blocking discrepancy.
Receipts never authorize legacy-table deletion automatically. MV averages are proved from the
exact original source operands and match durations, reduced in the same fixed
`(match_id, workspace_member_id)` order as native data; the canonical result must match bit-for-bit.
Reports retain each changed unordered legacy average, its FLOAT8 bits, the canonical value and bits,
and its actual delta, plus the changed-row count and maximum absolute delta. That raw drift is
diagnostic evidence, not a numeric tolerance or permission to change stored facts. Facts, events,
identities, hashes, official results
and best values remain exact; the resident MV must also match its native defining query, including
both float bit patterns.

Best-holder ranking keeps the existing best-value direction and latest-match criteria, then chooses
the lowest `workspace_member_id` in a full tie. An original bound-head MV may have selected the other
legitimate tied holder: forward upgrade accepts that metadata only when it exactly matches an
independently proven source candidate with the same best value and latest match. The upgrade records
the exact derived row before and after applying the stable tie-break, without rewriting facts,
official results or prior receipts. A different username or other metadata is never a blanket waiver.

Historical sources initially have `raw_status=unverified`; this is independent of processing status.
After initial receipt capture, inspect actual bytes and review the resulting proposal:

```console
uv run python scripts/stats01_prepare.py --verify-native-raw --report native-proposal.json
uv run python scripts/stats01_prepare.py --apply-native-raw --manifest native-reviewed.json --manifest-sha256 REVIEWED_SHA256 --report native-applied.json
```

The reviewed copy must include a nonempty `review`; its SHA binds the exact target and state.
Verification preserves known hashes, fills only genuinely unknown hashes from inspected bytes,
and distinguishes missing/conflicting sources from access errors. Shared ambiguous parse provenance
remains unverified. Downloads authorize first and check both source availability and actual SHA-256;
retry refuses unavailable, unbound or ambiguously shared historical observations before replacement.
Reconcile again after classification: audited changes return exit2, not an unchanged-data claim.


App profile/compare aggregates use deterministic native observation order. Their compatibility
proof preserves the old goldens and verifies operand bits, denominators and bounded binary64
reduction error; a hundredth-place display change must follow the unchanged rounding of that
proven aggregate. This is not a general numeric tolerance or permission to change stored facts,
rank/threshold outcomes, best values/owners or metadata.
The four captured achievement weighted-rate metrics use a separate exact-operand proof for the
same deterministic reduction; condition eligibility, ranks, thresholds, evidence and awards
still require exact parity.
Baseline inputs use stable `(match_id, global user_id)` order. Their original golden is retained;
a SHA-pinned frozen-source capture independently supplies only the canonical-order mean/std and
direct impact/overperformance differences. Native outputs must match that reference exactly,
including float bits; there is no additional baseline/score tolerance.

Bulk achievement-result insertion records only IDs returned by PostgreSQL. Reserved IDs discarded
by `ON CONFLICT DO NOTHING` never become receipt owners; their absence is not creation evidence.

Wire/runtime changes:

- Parsed matches belong directly to an authoritative encounter. A nullable unique `encounter_game_id`
  carries only a proven game association; `source_map_index` preserves the original claim separately.
  Obsolete match `source` and `code` fields are removed; replay codes and official result sources remain.
- A match lists every participant it observed (any number, `participants`), in historical encounter slot order,
  not log array order; each carries its own `source_position`, optional `tournament_team_id`, the bound game's
  official `result` and its observed segment-0 `team_facts` (an unobserved fact is an absent key, never zero). There
  is no home/away pair. The original 7,348-match parity snapshot contained 3,691 reversed observations. Analytics
  retains original `source_position`; observed scores never replace official results. Only a proven game determines
  map ordering; unbound observations remain visible as unordered history and continue to contribute ordinary
  statistics.
- `GET /api/v1/matches/{id}` adds a `statistics` document of the match's members (event-only members included),
  segments (positive only; segment 0 is the whole match) and every fact at every grain with the characters the facts
  name, and `GET /api/v1/matches/{id}/kill-feed` serves the whole event timeline; both use the match's own discipline,
  independently of nullable source-team metadata or current rosters. Deleted source teams do not remove observed
  numbers, and a dossier includes each observation only once across historical seats. User match rows carry the
  viewer's whole-match `facts` and every observed member's `member_totals`; achievement links carry `participants`.
- Admin writes reject obsolete fields, arbitrary team rebinding and maps conflicting with the game.
  New uploads use real content hashes and stored object references; unresolved valid uploads remain
  `awaiting_link`, not falsely successful. Downloads use the exact stored key.
  Order-dependent achievement rules defer uncertain series without granting new or revoking existing awards.
- A member merge with overlapping observations in the same match returns a conflict, not summed or
  deduplicated data. Audit counts are `stats_matches`, `stats_players`, `stats_facts`, `stats_events`.
  Rule/outbox dependencies use native `stats.*` names.
- Creation, ingestion, backfill, edits, merges and deletes stage bounded before/after evidence in
  the existing transaction. New workspace-member identities use creation-only evidence; reuse or
  revival does not authorize an identity change.

Dev refreshes use a selected Moscow production dump in isolated `owt_dev`; production
`anak_v5` is never the migration target. Keep the working home `anak_dev` and its stack until
the isolated copy, immutable receipt and backup are verified. Retain the original dump, exact
source bundles and verification evidence. Retained statistics storage still requires the later
reviewed removal gate. See [the dev-site runbook](../docs/dev-site.md) for the paired cutover.
