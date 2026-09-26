# Contributing to OWT

This document covers how to get a change into the repository: where code belongs, which
checks gate it, and how documentation is expected to age. Setup instructions live in
[`README.md`](./README.md); the system-level picture lives in
[`docs/architecture.md`](./docs/architecture.md).

## Branches and releases

- `develop` is the working branch. Feature work branches off it.
- `master` is the release source. CI runs on every pull request and on pushes to `master`.
- Publishing a GitHub **release** triggers [`deploy-production.yml`](./.github/workflows/deploy-production.yml),
  which re-runs the backend lint, backend test, gateway and frontend workflows as gates before
  deploying. A red gate blocks the deploy; nothing else does.

## Commit messages

Conventional commits, with a domain scope:

```
type(scope): imperative subject in lower case
```

- `type` — `feat`, `fix`, `refactor`, `test`, `style`, `chore`, `docs`.
- `scope` — the domain the change lives in, not the directory: `tournament`, `draft`,
  `registration`, `roster`, `bracket`, `standings`, `pre-game`, `stream`, `rbac`, `admin`,
  `balancer`, `divisions`, `pick-ban`.
- Subject says what the code now does, not what you did to it.
  `fix(draft): rank a player on their own role, not on their best one` — not
  `fix(draft): fix ranking bug`.

## Where code goes

Every backend service follows one layering, described in
[`backend/ARCHITECTURE.md`](./backend/ARCHITECTURE.md):

```
rpc → services → domain → repository → models
```

- New domain logic goes in the layer that rule assigns it, in the service that owns the data.
  Ownership is per Postgres schema; see [`docs/architecture.md`](./docs/architecture.md) §5.
- Cross-service code goes in `backend/shared/`, subject to
  [`backend/docs/repository-boundaries.md`](./backend/docs/repository-boundaries.md):
  repositories take an `AsyncSession`, return ORM rows, flush but never commit, and import no
  Pydantic schema, cache client, outbox publisher, or service settings.
- `app-service` additionally enforces a sub-domain hierarchy through import-linter — see
  [`backend/docs/architecture/layering.md`](./backend/docs/architecture/layering.md).
- The gateway is the only HTTP/WebSocket surface. A new REST route is a route entry plus an
  RPC method, never a new listening port; see [`gateway/README.md`](./gateway/README.md).

## Database changes

One Alembic project, `backend/migrations/`, over one database shared by every service.

1. Change the ORM model in `backend/shared/models/<domain>/`.
2. Autogenerate a revision, review it by hand — autogenerate does not see server defaults,
   partial indexes, or data moves.
3. `make migrate` applies `upgrade head` inside `app-svc`.
4. Commit the generated file, then regenerate the data model:
   `cd backend && uv run python scripts/export_erd.py`. The entity diagrams in
   [`docs/database_erd.md`](./docs/database_erd.md) come from `Base.metadata`; the prose
   around them does not. CI fails if the two disagree.

**Destructive migrations are gated.** A migration that drops a column or table must not run
from a plain `upgrade head` while readers still reference it. The 2026-07-05 production
incident came from exactly that; the pattern for doing it safely is in
[`docs/challonge_normalization_phase2_runbook.md`](./docs/challonge_normalization_phase2_runbook.md).

## Generated artifacts

Three files are committed but derived, and CI fails if they drift:

| Artifact | Source of truth | Regenerate |
| --- | --- | --- |
| Gateway OpenAPI manifest | the services' Pydantic models | `cd backend && bash scripts/export_openapi_schemas.sh` |
| `frontend/src/lib/divisions/ow-ladder.generated.json` | `backend/shared/domain/ow_ladder.py` | `cd backend && uv run python scripts/export_ow_ladder.py` |
| Entity diagrams in `docs/database_erd.md` | `Base.metadata` (`backend/shared/models/`) | `cd backend && uv run python scripts/export_erd.py` |

A new model **package** needs a new section in `docs/database_erd.md` — a heading, a sentence
saying what the domain is for, and an empty `<!-- ERD:auto <package> -->` / `<!-- /ERD:auto -->`
pair. The generator refuses to run until it has somewhere to put the diagram, which is the
point: a new domain gets one sentence of explanation or it does not ship.

## Checks before you push

Install the hooks once — `pre-commit install` — which runs ruff plus file hygiene on staged
files. Then, per area you touched:

```bash
# Backend
cd backend
uv run bash scripts/lint.sh                       # ruff check + ruff format --check
bash scripts/export_openapi_schemas.sh --check
uv run python scripts/export_ow_ladder.py --check
uv run python scripts/export_erd.py --check
cd .. && make test                                 # pytest, per service, with coverage

# Frontend
cd frontend
bun run typecheck
bun run lint
bun run lint:design                                # design-token compliance
bun run test:vitest

# Gateway
cd gateway
go mod tidy -diff
gofmt -l .
go vet ./...
go test -race ./...

# Docs
python3 scripts/check_doc_links.py                 # relative links resolve
```

Type checking (`mypy` / `ty`) is deliberately **not** part of the backend gate. `next build`
runs only on `master`, not on pull requests — do not run it locally to test a change;
`bun run typecheck` and `bun run lint` are the fast signal.

The frontend runs one test runner. `vitest.config.ts` collects `src/**/*.test.ts(x)` by glob,
so a new test file runs the moment it is written — nothing to register anywhere.

## Documentation

Documentation is English. The archive under `docs/plans/`, `docs/superpowers/`,
`docs/reviews/` and the in-flight project folders are the exception: they are frozen or
in-flight working documents and are left in whatever language they were written in.

Three kinds of document, three different lifecycles:

| Kind | Where | Rule |
| --- | --- | --- |
| Evergreen reference | `docs/*.md`, `backend/docs/`, component `README.md` | Describes the system as it is. Updated in the same commit as the change it describes. |
| Operational runbook | linked from [`docs/README.md`](./docs/README.md) | A procedure an operator follows under pressure. Commands verbatim, preconditions explicit. |
| Design / plan | `docs/plans/YYYY-MM-DD-<slug>.md`, or `docs/<slug>/` for a multi-file effort | Point-in-time. When the work ships, anything that must outlive it moves into an evergreen document; the plan is then dead and stops being maintained. |

`docs/plans/` is the one place for new plans. `docs/superpowers/` and `docs/reviews/` are a
frozen archive from before that rule — read them, never add to them, and expect their internal
links to have rotted.

Relative links are gated ([`.github/workflows/ci-docs.yml`](./.github/workflows/ci-docs.yml)):
a link to a file that does not exist fails the build, except inside the frozen archive, where
the rot is recorded rather than repaired.

Do not add a fact to a plan and nowhere else. A plan is read once, by the person implementing
it; six months later the only document anyone opens is the evergreen one.

Start from [`docs/README.md`](./docs/README.md) — it is the map, and a new evergreen document
that is not linked from it does not exist.
