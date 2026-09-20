# Repository Boundaries

Shared CRUD repositories live in `shared.repository` and are the preferred way
to access ORM rows from multiple services. This is the repository layer's slice of the
full rpc → services → domain → repository → models stack described in
[`backend/ARCHITECTURE.md`](../ARCHITECTURE.md).

## Repository Rules

- Repositories accept an `AsyncSession` and return ORM models or row tuples.
- Repositories do not import FastAPI, Pydantic schemas, Redis/cache clients,
  outbox publishers, or service settings.
- Repository write methods flush only. Services, use cases, or routes own
  `commit` and rollback decisions.
- Keep large analytical queries in query/service modules. Do not hide CTE,
  window, leaderboard, ML feature extraction, achievement condition, or
  recalculation queries behind CRUD repositories.

## Exemptions

`tests/test_repository_boundaries.py` carries two lists, because "allowed" and
"not migrated yet" are different claims:

- `APPROVED_DIRECT_WRITE_FILES` — access that is intentionally not CRUD: outbox
  draining, bracket advancement internals, analytics materialization, bulk
  association-table updates, append-only journals (`realtime/emit.py`,
  `notifications.py`), executemany ingest (`match_logs/flows.py`), and
  synchronous ORM collection replacement (`stage_common.py`).
- `PENDING_REPOSITORY_MIGRATION` — direct writes that predate their repository.
  Every entry is a line to delete once the repository method exists, not a
  pattern to copy.

Both are ratcheted: an entry whose file no longer writes directly — or no longer
exists — fails the suite, so finishing a migration forces the line out. Without
that ratchet the list rotted unnoticed into twelve entries for files deleted
with `auth-service` and the old `tournament-service` HTTP routes, while the
services that replaced them went unscanned.

The ratchet only guards entries that exist. It does NOT fail a file that starts
writing directly and is in neither list — `test_new_direct_db_writes_go_through_shared_repositories`
does, and that is the test to keep green: nine files had accumulated there
unnoticed, and while it was red it guarded nothing. A red boundary suite is the
same as no boundary suite.
