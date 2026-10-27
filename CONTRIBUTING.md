# Contributing to OWT

This document covers how to get a change into the repository: where code belongs, which
checks gate it, and how documentation is expected to age. Setup instructions live in
[`README.md`](./README.md); the system-level picture lives in
[`docs/architecture.md`](./docs/architecture.md).

## MCP tooling

Project MCP servers are configured in [`.mcp.json`](./.mcp.json) and
[`opencode.jsonc`](./opencode.jsonc). SonarQube MCP is intentionally not configured:
starting an AI client must not launch `sonarsource/sonarqube-mcp` in Docker.
After changing MCP configuration, run `/mcp reload` in already-open OMP sessions;
otherwise their existing server connections can relaunch removed containers.

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
- `app-service` and `stats-service` (its public read surface) additionally enforce a sub-domain hierarchy through import-linter — see
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
from a plain `upgrade head` while readers still reference it — the 2026-07-05 production
incident came from exactly that. Ship it in two deploys:

1. **Expand/migrate:** move every reader and writer off the column; keep the column on the DB
   and the ORM model.
2. **Contract:** the drop migration is a no-op unless an env flag is set
   (`OWT_APPLY_<THING>_DROP=1`), and it removes the ORM field in the same deploy. Verify the
   deployed image, not the checkout, and check data parity before applying. Never run
   `upgrade head` without the flag first: that stamps the revision as applied and the real
   drop then needs a fresh migration. Safer, as `legacy01` does: without the flag, raise when the
   storage still holds rows (nothing dropped, nothing stamped) and drop when it is empty.

## Generated artifacts

Three files are committed but derived, and CI fails if they drift:

| Artifact | Source of truth | Regenerate |
| --- | --- | --- |
| Gateway OpenAPI manifest | the services' Pydantic models | `cd backend && bash scripts/export_openapi_schemas.sh` |
| `frontend/src/disciplines/overwatch/ladder/ow-ladder.generated.json` | `backend/shared/disciplines/overwatch/ladder.py` | `cd backend && uv run python scripts/export_ow_ladder.py` |
| Entity diagrams in `docs/database_erd.md` | `Base.metadata` (`backend/shared/models/`) | `cd backend && uv run python scripts/export_erd.py` |

A new model **package** needs a new section in `docs/database_erd.md` — a heading, a sentence
saying what the domain is for, and an empty `<!-- ERD:auto <package> -->` / `<!-- /ERD:auto -->`
pair. The generator refuses to run until it has somewhere to put the diagram, which is the
point: a new domain gets one sentence of explanation or it does not ship.

## Checks before you push

Install the hooks once — `cd backend && uv run pre-commit install` (unset a stale `core.hooksPath`
first, pre-commit refuses to install over it). On commit: ruff `--fix` + format and file hygiene on
staged files. On push: the CI ruff gate (`ruff check` + `ruff format --check` over `backend/`), with
the ruff version from `backend/uv.lock`. Then, per area you touched:

```bash
# Backend
cd backend
uv run bash scripts/lint.sh                       # ruff check + ruff format --check
uv run bash scripts/typecheck.sh                  # ty, one run per package
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

The backend type check is `ty` against `backend/ty-gate.toml`: every rule is an error except the
ones listed there, which already had hits when the gate landed (their counts are beside them). Fix
a listed rule's hits, then delete its line. The backend suites run in CI against a real Postgres
(the `docker-compose.test.yml` container, as a service), so DB-integration tests run there rather
than skip. The exception is the historical migration cutover proofs in `backend/tests`
(`test_stats01_*`, `test_enclayer01_*`, `test_discipline01*_upgrade`, …): the parts that rebuild
scratch databases at old revisions take hours, so they skip unless
`shared.testing.db.migration_proofs_enabled()` — `OWT_MIGRATION_PROOFS=1` on that ephemeral test
Postgres. Their tests that need no scratch database still run.
CI proves the current chain with `alembic upgrade head` instead. `next build` runs only on
`master`, not on pull requests — do not run it locally to test a change; `bun run typecheck` and
`bun run lint` are the fast signal.

The frontend runs one test runner. `vitest.config.ts` collects `src/**/*.test.ts(x)` by glob,
so a new test file runs the moment it is written — nothing to register anywhere.

## Documentation

Documentation is English.

`docs/` holds documentation and nothing else. Two kinds of document, two lifecycles:

| Kind | Where | Rule |
| --- | --- | --- |
| Evergreen reference | `docs/*.md`, `backend/docs/`, component `README.md` | Describes the system as it is. Updated in the same commit as the change it describes. |
| Operational runbook | linked from [`docs/README.md`](./docs/README.md) | A procedure an operator follows under pressure. Commands verbatim, preconditions explicit. |

Designs, plans, specs and reviews are not committed. Draft them in gitignored scratch
(`.claude/`, `.superpowers/`); record the decisions and their reasons in Graphiti, group
`anak-tournaments`. The documents removed from `docs/` on 2026-09-27 are there as one
episode each, and in full at `git show 50b83c88f537:<path>` — code comments citing
`docs/plans/…`, `docs/superpowers/…` or `docs/reviews/…` refer to that commit.

Relative links are gated ([`.github/workflows/ci-docs.yml`](./.github/workflows/ci-docs.yml)):
a link to a file that does not exist fails the build.

Do not record a fact only in a plan or a Graphiti episode. A plan is read once, by the person
implementing it; six months later the only document anyone opens is the evergreen one.

Start from [`docs/README.md`](./docs/README.md) — it is the map, and a new evergreen document
that is not linked from it does not exist.
