# Repository Boundaries

Shared CRUD repositories live in `shared.repository` and are the preferred way
to access ORM rows from multiple services.

## Repository Rules

- Repositories accept an `AsyncSession` and return ORM models or row tuples.
- Repositories do not import FastAPI, Pydantic schemas, Redis/cache clients,
  outbox publishers, or service settings.
- Repository write methods flush only. Services, use cases, or routes own
  `commit` and rollback decisions.
- Keep large analytical queries in query/service modules. Do not hide CTE,
  window, leaderboard, ML feature extraction, achievement condition, or
  recalculation queries behind CRUD repositories.

## Legacy Exceptions

`tests/test_repository_boundaries.py` contains the current allowlist for direct
DB writes that were present before this migration. New direct write files should
not be added to that allowlist unless the access is intentionally not CRUD, such
as outbox draining, bracket advancement internals, analytics materialization, or
bulk association-table updates.
