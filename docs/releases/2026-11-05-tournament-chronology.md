# One tournament chronology: release note

Every read that orders tournaments as time now uses one key. Ids follow creation, not play, and a tournament can have no
dates, so the old orders (`start_date` with `NULLS LAST`, bare `id`, the id range in the ML backfill) put tournaments in
a different order in different places. Design: `docs/superpowers/specs/2026-11-05-tournament-flow-design.md` §11.1.

## What changed

- **The key.** `(coalesce(start_date, created_at), coalesce(end_date, start_date, created_at), id)`, built once in
  `backend/shared/core/chrono.py` (`tournament_chrono_key()` in SQL, `chrono_sort_key(row)` in Python). It is never NULL,
  so no `NULLS LAST` / `NULLS FIRST` remains where it is used.
- **Where it applies.** Analytics and ML (v1 histories and streaks, timelines, windows and replays, chronological
  splits), achievements (streaks, division change), newcomer status in the balancer, and the stats and tournament-service
  "newest first" reads: the rank-autofill lookback and its three source queries, the registration history, the history
  and average-division tournament lists, and the dashboard backlog and trends.
- **Undated tournaments** now sit at their creation time (they used to sort after every dated tournament). A start-date
  tie is broken by the end date, then the id.
- **`ml.cli backfill`** takes `--from/--to YYYY-MM-DD` (UTC start days) instead of an id range; the shift-recompute
  runbook uses it.
- **`TimeSeriesSplit.from_ids`** refuses tournament ids that are not in chronology order instead of splitting them.
- **Achievement rule cutoffs** compare chronology, not ids. A rule whose cutoff tournament was deleted applies to every
  tournament; the old id comparison kept skipping the lower ids.

## Why

A tournament created late but played early, or one with no dates, was treated as the newest by some reads and the oldest
by others. Rolling windows, streaks, "previous tournament" lookups and the ML time split read the wrong history for it.

## Operator steps

No migration, no config change, no OpenAPI/RPC change. Deploy the analytics, balancer, stats and tournament services
from one SHA: they must agree on the order, otherwise a read in one service and a write in another disagree for the
tournaments below.

Optional, before deploying, to see how many tournaments change place (those with no start date; start-date ties also
move):

```sql
SELECT count(*) FROM tournament.tournament WHERE start_date IS NULL;
```

## Not in this release

- **Recomputing stored analytics.** Points, Linear, OpenSkill and ML rows computed under the old order stay as they
  are until the recompute queued for the league merge (spec §15.5).
- Id-only list and pagination orders, the `max(tournament_id)` "last tournament" aggregates in the achievement reads,
  and frontend sorting are unchanged.
