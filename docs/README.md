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
| [`design-book.md`](./design-book.md) | Frontend design system — tokens, type scale, colour roles, layout patterns |
| [`frontend-zones.md`](./frontend-zones.md) | Frontend route zones (`web` / `admin` / `tools`), the three import rules CI enforces, and the per-zone i18n message bundles |
| [`glossary.md`](./glossary.md) | Domain vocabulary used across code, API and UI |
| [`business-logic-inventory.md`](./business-logic-inventory.md) | Domain rules and invariants: lifecycle, registration, admission, roster, balancer/draft, brackets, pick-ban, logs, achievements, analytics |
| [`api-rate-limits.md`](./api-rate-limits.md) | Client-facing API quota contract: what is metered, the refusal shape, reading your remaining budget |
| [`../frontend/src/app/(site)/docs/_content/`](../frontend/src/app/%28site%29/docs/_content/) | Player, organizer and developer guides served at `/docs`, one MDX file per locale (`ru`, `en`). Titles and order live in `frontend/src/app/(site)/docs/nav.ts`. The `/docs/dev/schema` page renders `schema.generated.json`, written by `backend/scripts/export_erd.py` alongside `database_erd.md` |

### Per component

| Component | Document |
| --- | --- |
| Backend, all services | [`../backend/README.md`](../backend/README.md) |
| Backend code layering (`rpc → services → domain → repository → models`) | [`../backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md) |
| Repository-layer rules | [`../backend/docs/repository-boundaries.md`](../backend/docs/repository-boundaries.md) |
| `app-service` sub-domain hierarchy (import-linter enforced) | [`../backend/docs/architecture/layering.md`](../backend/docs/architecture/layering.md) |
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
[`parser-service`](../backend/parser-service/README.md),
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
