# Security Policy

## Reporting a vulnerability

Report privately through GitHub's
[**Report a vulnerability**](https://github.com/CraazzzyyFoxx/overwatch-tournaments/security/advisories/new)
form. Do not open a public issue, and do not disclose the finding until a fix is released.

Include what you have: affected component (gateway, a backend service, frontend, nginx edge),
the request or steps that reproduce it, and what an attacker gets. A proof of concept against
your own local stack is worth more than a description.

Expect a first response within seven days.

## Scope

The code in this repository: the Go gateway, the Python services under `backend/`, the Next.js
frontend, the nginx edge configuration, the Compose deployment files, and the CI workflows.

Of particular interest, because these are the trust boundaries:

- **Authentication** — JWT issuance and validation, OAuth callbacks, session cookies, API keys,
  service tokens (`backend/identity-service`, `gateway/internal/auth`).
- **Tenant isolation** — anything that lets one workspace read or write another's data. Every
  business table is scoped by `workspace_id`; a missing filter is a vulnerability, not a bug.
- **Authorization** — the grant-only RBAC catalog and its deny overlay (`backend/shared/rbac/`),
  and the gateway's route and WebSocket topic ACLs (`gateway/internal/acl`).
- **Untrusted input** — uploaded match logs, Challonge and Google Sheets sync payloads, Discord
  bot attachments, and anything reaching the parser.

Out of scope: the live deployment at `owt.craazzzyyfoxx.me` (do not test against it), the
hosting infrastructure in front of the nginx edge, and third-party services
(Discord, Twitch, Battle.net, Challonge, OverFast).

## Self-hosting

The credentials shown in [`README.md`](./README.md) are development-only. A deployment exposed
to a network must, at minimum:

- replace `JWT_SECRET_KEY` with at least 32 random characters, and every other template secret;
- terminate TLS in front of the nginx edge;
- restrict the admin API documentation endpoint;
- set the allowed WebSocket origins explicitly rather than leaving them open;
- keep every environment file untracked.

Backup and restore procedures are in [`docs/backup-rustfs.md`](./docs/backup-rustfs.md).
