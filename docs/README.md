# OWT documentation

The map. Every evergreen document in the repository is reachable from here; anything not
linked below is either component-local or archive.

## Start here

| I want to… | Read |
| --- | --- |
| Understand what the platform is and run it locally | [`../README.md`](../README.md) |
| Understand how the pieces fit together | [`architecture.md`](./architecture.md) |
| Get a change merged | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Look up a domain term | [`glossary.md`](./glossary.md) |
| Report a vulnerability | [`../SECURITY.md`](../SECURITY.md) |

## Reference

The system as it is. These are updated in the same commit as the change they describe.

| Document | Covers |
| --- | --- |
| [`architecture.md`](./architecture.md) | Components, request flow, RabbitMQ RPC and events, multitenancy, deployment topology, observability |
| [`database_erd.md`](./database_erd.md) | Every table, column and relationship, one diagram per model package. Diagrams generated from `Base.metadata` and gated in CI; prose hand-written |
| [`users-identity.md`](./users-identity.md) | Identity model: `auth.user` vs `players.user`, shadow and virtual players, workspace membership, account linking |
| [`design-book.md`](./design-book.md) | Frontend design system — tokens, type scale, colour roles, layout patterns |
| [`glossary.md`](./glossary.md) | Domain vocabulary used across code, API and UI |

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
(and its native solver, [`moo_core`](../backend/balancer-service/native/mix_balancer/README.md)),
[`analytics-service`](../backend/analytics-service/README.md),
[`stream-service`](../backend/stream-service/README.md),
[`discord-service`](../backend/discord-service/README.md).

## Runbooks

Procedures for an operator. Commands are meant to be run verbatim.

| Runbook | When |
| --- | --- |
| [`backup-rustfs.md`](./backup-rustfs.md) | PostgreSQL dumps, two-site S3 replication, verification, restore |
| [`dev-site.md`](./dev-site.md) | The dev deployment at `dev.owt.craazzzyyfoxx.me` — what differs from production, deploy, data refresh |
| [`challonge_normalization_phase2_runbook.md`](./challonge_normalization_phase2_runbook.md) | Running the gated destructive migration — and the pattern for any future one |
| [`superpowers/plans/2026-07-06-subdomains-ops-runbook.md`](./superpowers/plans/2026-07-06-subdomains-ops-runbook.md) | Workspace subdomains and custom domains: DNS, certificates, verification |
| [`../backend/analytics-service/docs/runbook-shift-recompute.md`](../backend/analytics-service/docs/runbook-shift-recompute.md) | Recomputing OpenSkill rating shifts |

## In-flight work

Design and plan documents for work currently being implemented. They are point-in-time and
stop being maintained once the work ships.

- [`tournament-redesign/`](./tournament-redesign/) — public tournament page redesign

## Archive

Historical designs, plans, inventories and reviews. **Frozen** — read for the reasoning behind
a decision, never as a description of the current system, and never extend them. Internal
links inside the archive have rotted and are not repaired.

- [`plans/`](./plans/) — designs and implementation plans, dated. New plans go here.
- [`superpowers/`](./superpowers/) — an earlier split of the same thing into `specs/` (design)
  and `plans/` (implementation). Superseded by `plans/`.
- [`reviews/`](./reviews/) — point-in-time audits, e.g. the 2026-07-03 backend security and
  performance review.

Git history is part of the archive: `git log -- <file>` on a spec answers "why is it like
this" better than any of these documents.

## Conventions

- **English.** Reference documents, runbooks and component READMEs are English. The archive
  and in-flight project documents are left in whatever language they were written in.
- **A document has one job.** Reference describes the present, a runbook describes a
  procedure, a plan describes an intention. A file that does two of these becomes stale in
  half of itself.
- **Facts have one home.** When work ships, what must outlive it moves into the reference
  document; the plan is not that home.
- **Unlinked is invisible.** A new evergreen document that is not in this file does not exist.
