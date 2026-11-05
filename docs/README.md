# OWT documentation

The map. Every document in the repository is reachable from here; anything not linked below
is component-local.

## Start here

| I want to… | Read |
| --- | --- |
| Understand what the platform is and run it locally | [`../README.md`](../README.md) |
| Understand how the pieces fit together | [`architecture.md`](./architecture.md) |
| Get a change merged | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Look up a domain term | [`glossary.md`](./glossary.md) |
| Look up a domain rule (phases, admission, pick-ban, …) | [`business-logic-inventory.md`](./business-logic-inventory.md) |
| Report a vulnerability | [`../SECURITY.md`](../SECURITY.md) |

## Reference

The system as it is. These are updated in the same commit as the change they describe.

| Document | Covers |
| --- | --- |
| [`architecture.md`](./architecture.md) | Components, request flow, RabbitMQ RPC and events, multitenancy, deployment topology, observability |
| [`database_erd.md`](./database_erd.md) | Every table, column and relationship, one diagram per model package. Diagrams generated from `Base.metadata` and gated in CI; prose hand-written |
| [`users-identity.md`](./users-identity.md) | Identity model: `auth.user` vs `players.user`, shadow and virtual players, workspace membership, account linking |
| [`../frontend/DESIGN.md`](../frontend/DESIGN.md) | Frontend design system — tokens, type roles, the chip policy, components to reuse, layout and canonical patterns. [`design-book.md`](./design-book.md) maps its old section numbers there |
| [`frontend-zones.md`](./frontend-zones.md) | Frontend route zones (`web` / `admin` / `tools`), the three import rules CI enforces, and the per-zone i18n message bundles |
| [`glossary.md`](./glossary.md) | Domain vocabulary used across code, API and UI |
| [`business-logic-inventory.md`](./business-logic-inventory.md) | Domain rules and invariants: lifecycle, registration, admission, roster, balancer/draft, brackets, pick-ban, logs, achievements, analytics |
| [`api-rate-limits.md`](./api-rate-limits.md) | Client-facing API quota contract: what is metered, the refusal shape, reading your remaining budget |
| [`tournament-voice-channels.md`](./tournament-voice-channels.md) | Tournament Discord voice channels: the plan, the bot's reconciler, hub routing, Individual Swiss round slots, the admin API |
| [`../frontend/src/app/(site)/docs/_content/`](../frontend/src/app/%28site%29/docs/_content/) | Player, organizer and developer guides served at `/docs`, one MDX file per locale (`ru`, `en`). Titles and order live in `frontend/src/app/(site)/docs/nav.ts`. The `/docs/dev/schema` page renders `schema.generated.json`, written by `backend/scripts/export_erd.py` alongside `database_erd.md` |

### Per component

| Component | Document |
| --- | --- |
| Backend, all services | [`../backend/README.md`](../backend/README.md) |
| Backend code layering (`rpc → services → domain → repository → models`) | [`../backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md) |
| Repository-layer rules | [`../backend/docs/repository-boundaries.md`](../backend/docs/repository-boundaries.md) |
| `app-service` and `stats-service` read-surface sub-domain hierarchies (import-linter enforced) | [`../backend/docs/architecture/layering.md`](../backend/docs/architecture/layering.md) |
| Shared kernel — models, tenancy, RBAC, messaging, observability | [`../backend/shared/README.md`](../backend/shared/README.md) |
| Gateway — routes, JWT, RPC dispatch, realtime hub, caching | [`../gateway/README.md`](../gateway/README.md) |
| Frontend — conventions, scripts, structure | [`../frontend/README.md`](../frontend/README.md) |
| Frontend design conventions in code | [`../frontend/DESIGN.md`](../frontend/DESIGN.md) |
| UI term glossary, per locale | [`../frontend/src/i18n/GLOSSARY.md`](../frontend/src/i18n/GLOSSARY.md) |
| Monitoring — Prometheus, Grafana, Loki, Tempo, alerts | [`../monitoring/README.md`](../monitoring/README.md) |
| Load testing — Locust scenarios, seeding, reports | [`../loadtests/README.md`](../loadtests/README.md) |

Individual services document their own RPC surface and scheduled work:
[`app-service`](../backend/app-service/README.md),
[`identity-service`](../backend/identity-service/README.md),
[`tournament-service`](../backend/tournament-service/README.md),
[`stats-service`](../backend/stats-service/README.md),
[`balancer-service`](../backend/balancer-service/README.md)
(and its native solvers, [`balancer_native`](../backend/balancer-service/README.md#native-solver)),
[`analytics-service`](../backend/analytics-service/README.md),
[`stream-service`](../backend/stream-service/README.md),
[`discord-service`](../backend/discord-service/README.md).

## Runbooks

Procedures for an operator. Commands are meant to be run verbatim.

| Runbook | When |
| --- | --- |
| [`production-host.md`](./production-host.md) | Sizing a production host (minimum 4 vCPU / 8 GB / 80 GB SSD); running it with the bundled Postgres + pgBouncer (`db` profile) |
| [`backup-rustfs.md`](./backup-rustfs.md) | Daily PostgreSQL dumps to S3, alerts, restore |
| [`disk-cleanup.md`](./disk-cleanup.md) | Daily disk cleanup on a production host: stale docker images, build cache, compose-level log caps |
| [`dev-site.md`](./dev-site.md) | A second deployment of the stack (dev/staging): what differs from production, deploy, data refresh |
| [`workspace-domains.md`](./workspace-domains.md) | Workspace subdomains and custom domains: DNS, certificates, verification |
| [`../backend/analytics-service/docs/runbook-shift-recompute.md`](../backend/analytics-service/docs/runbook-shift-recompute.md) | Recomputing OpenSkill rating shifts |
| [`encounter-layer-v1-release.md`](./encounter-layer-v1-release.md) | Shipping the encounter layer V1: breaking API changes, the preflight → upgrade → recompute → reconcile cutover, what is unmeasured |
| [`multi-game-p1-catalog-release.md`](./multi-game-p1-catalog-release.md) | Shipping the multi-game P1 catalog: wire breaks, preflight/reconcile, cache and queue drain, hero-stats view population, dev/staging resets |
| [`multi-game-p2-roles-release.md`](./multi-game-p2-roles-release.md) | Shipping the P2 role ontology and team formats: RoleRef wire breaks, preflight classes 2–8, reconciliation, dev/staging resets |
| [`multi-game-p3-ranks-release.md`](./multi-game-p3-ranks-release.md) | Shipping P3 ranks and identity: native modules, role-ID storage, independent grid defaults, Riot/provider wire contracts, retained migration evidence and phase verification limits |
| [`releases/2026-10-15-multi-game-p5-ingest.md`](./releases/2026-10-15-multi-game-p5-ingest.md) | Shipping P5 canonical ingest: the `owt.match/1` protocol and API keys, idempotency and status/error contracts, observed vs official results, `stats-svc`/`stats-worker` and `STATS_DISCIPLINES`, the cutover matrix, P9 queue drain and rollback, P4 data blockers, the local live-smoke recipe |
| [`releases/2026-10-18-multi-game-p6-achievements-analytics.md`](./releases/2026-10-18-multi-game-p6-achievements-analytics.md) | Shipping P6: portable achievement format v2 (v1/`hero_id` rejected), `achievement06` forward-only, discipline on every achievement API, analytics scoping with no LoL ML fallback, the P9 artifact-conversion runbook (exact allowlist, two-image procedure, rollback), verification run and deferred items |
| [`releases/2026-10-21-backend-cleanup.md`](./releases/2026-10-21-backend-cleanup.md) | Shipping the backend cleanup: the `balancer` → `registration` / `mix` / `draft` schema split (`schemasplit01`, one-SHA deploy), removed analytics/identity endpoints and queues (`quota0003`), settings no longer read, the gated legacy storage drop (`legacy01`) and its runbook |
| [`releases/2026-10-21-riot-lol.md`](./releases/2026-10-21-riot-lol.md) | Shipping Riot Sign-On and LoL native ranks: the shared `rank` schema (`rank01`, import-job key rewrite), Riot env and the RSO client, the LoL collector (off by default; dev keys expire in 24 h, PUUIDs re-resolve per key), rank wire renames and the `/game-accounts` route, operator steps |
| [`releases/2026-10-21-deadlock.md`](./releases/2026-10-21-deadlock.md) | Shipping Deadlock and Steam sign-in: the `deadlock` module (deadlock-api catalog, 66-tier ladder, batched rank collector, on by default), Steam OpenID login/link and handle formats, the Discord + Steam mix requirement, generic match import by external id (`stats.match_fetch`, `deadlock01`), a match's own game mode (`MatchDoc.mode`, `matchmode01`, a maintenance-window lock), operator steps and the live smoke |
| [`releases/2026-10-23-valorant.md`](./releases/2026-10-23-valorant.md) | Shipping VALORANT as a base module: the `valorant` discipline (valorant-api.com catalog, 25-tier ladder, organizer-entered ranks, Riot ID, one role, 5v5, the VCT Bo1 map veto preset), `valorant01`, operator steps and what is deferred (native ranks, match import, Bo3 sides) |
| [`releases/2026-10-21-rank-mapping-removal.md`](./releases/2026-10-21-rank-mapping-removal.md) | Removing the Overwatch rank mapping: `parser.rank_mapping` and the collector's Mapping tab gone, ranks always valued on the ladder, `owmapdrop01` recomputes overridden snapshots, collapses repeats and drops the setting |
| [`releases/2026-10-21-division-grid-defaults.md`](./releases/2026-10-21-division-grid-defaults.md) | A default division grid per game in every workspace (`defgrid01` backfill, provisioning on create/enable, the activation rule), create-from-version and `tournament_count` on the grid API, and the divisions page: all-games summary, New grid, the grid menu with detach-and-delete, game-aware copy |
| [`releases/2026-10-23-prod-cutover.md`](./releases/2026-10-23-prod-cutover.md) | Taking production from v1.48.1 through every cutover above in one maintenance window: the nginx maintenance page (`make maint-on/eta/off`, bypass cookie), pre-window checks and the step timings measured on dev, drain/backup/migrate/proof/start order, point of no return and restore |
| [`releases/2026-11-05-tournament-chronology.md`](./releases/2026-11-05-tournament-chronology.md) | One tournament chronology (start, end, id) for every time-ordered read: analytics/ML, achievements, newcomer status, stats and tournament reads; the date-range ML backfill and its runbook change; no migration |
| [`releases/2026-11-05-participant-result.md`](./releases/2026-11-05-participant-result.md) | `tournament.participant_result`: one result per member per finished tournament, backfilled, read by profile/overview/compare/titles, analytics and the Overwatch placement achievements; behaviour changes and the post-migration rollout (achievement evaluation per workspace, analytics recompute) |

## Designs, plans and reviews

Not kept here. Decisions and their reasons live in Graphiti, group `anak-tournaments`; drafts
live in gitignored scratch. The documents that used to sit under `docs/plans/`,
`docs/superpowers/`, `docs/reviews/`, `docs/<project>/` and `backend/docs/architecture/specs/`
are one Graphiti episode each, and in full at `git show 50b83c88f537:<path>`.

Git history answers "why is it like this" too: `git log -S <symbol>` finds the commit that
introduced it.

## Conventions

- **English.**
- **A document has one job.** Reference describes the present, a runbook describes a
  procedure. A file that does both becomes stale in half of itself.
- **Facts have one home.** When work ships, what must outlive it moves into the reference
  document; the plan is not that home.
- **Unlinked is invisible.** A new evergreen document that is not in this file does not exist.
