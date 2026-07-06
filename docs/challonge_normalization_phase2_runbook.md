# Challonge / predictions normalization — Phase 2 (contract) runbook

Phase 1 (code migration) is DONE and shippable: tournament-service, parser-service
and analytics-service no longer read or write the legacy Challonge columns /
`analytics.predictions` — everything goes through the normalized tables
(`challonge_source` / `challonge_participant_mapping` / `challonge_match_mapping`;
`standings_distribution`). The legacy columns/tables still EXIST in the DB and are
still declared on the ORM models (kept on purpose), so Phase 1 deploys safely.

Phase 2 = the destructive DROP. It is deliberately **gated fail-closed** (env
flags) and must NOT run via a plain `alembic upgrade head`. Root-cause of the
2026-07-05 prod incident: a deferred drop that ran on `upgrade head` before the
readers were migrated. See `lesson_gated_migration_in_linear_chain`.

## What Phase 2 drops
- `dbarch04b` (flag `OWT_APPLY_CHALLONGE_DROP=1`): `tournament/stage/encounter.challonge_id` + `tournament/stage.challonge_slug`, table `tournament.challonge_team`.
  - **NOT dropped:** `group.challonge_id`/`challonge_slug` — holds Challonge's per-group `match.group_id` routing value, has no `challonge_source` equivalent, still actively read/written. Keep it.
- `dbarch06` (flag `OWT_APPLY_PREDICTIONS_DROP=1`): `analytics.predictions`.

## Preconditions (all must hold on prod)
1. Phase 1 code is DEPLOYED (the running containers are built from a commit that
   includes commits `055f75fe`, `a80c99af`, `0b9206d7` and later). Verify the
   deployed image, not just the git checkout.
2. Remove the legacy ORM columns/models in the SAME deploy as the drop (they are
   currently kept): `Tournament/Stage/Encounter.challonge_id/slug`, the
   `ChallongeTeam` class + `Team.challonge` relationship + the `ChallongeTeam`
   imports in `app-service`/`balancer-service` `src/models/__init__.py`.
   (`AnalyticsPredictions` was already removed in `0b9206d7`.) Model and DB must
   drop together or `model_validate`/queries will drift.
3. Mapping-table parity confirmed on prod (the drop is data-safe because the
   values live in the mapping tables):
   ```sql
   -- every tournament/stage with a legacy challonge_id has a source row
   SELECT count(*) FROM tournament.tournament t
     WHERE t.challonge_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM tournament.challonge_source cs
                       WHERE cs.tournament_id=t.id AND cs.source_type='tournament');
   -- every challonge_team row has a participant mapping
   SELECT count(*) FROM tournament.challonge_team ct
     WHERE NOT EXISTS (SELECT 1 FROM tournament.challonge_participant_mapping pm
                       WHERE pm.challonge_participant_id=ct.challonge_id AND pm.team_id=ct.team_id);
   ```
   Both must be 0. (`dbarch04` re-backfills the mapping tables; run it if drift.)
4. Post-deploy log scan shows zero reads/writes of the legacy columns/table.

## Apply (prod)
Migrations are not baked into the images — `docker cp` them in, run with the
right workdir/env (see `lesson_gated_migration_in_linear_chain` for the exact
`docker compose exec ... -w /app` invocation). Prod is currently at
`alembic_version = dbarch05`; the gated migrations have NOT been stamped yet, so
the first `upgrade` WITH the flag executes the drop:

```bash
docker compose -f docker-compose.production.yml -p owt exec \
  -e POSTGRES_DB=anak_v5 -e OWT_APPLY_CHALLONGE_DROP=1 -e OWT_APPLY_PREDICTIONS_DROP=1 \
  -w /app app-svc alembic upgrade head
```

Do NOT run `alembic upgrade head` WITHOUT the flags first — that stamps
`dbarch04b`/`dbarch06` as no-ops, after which the real drop needs a fresh
migration (alembic won't re-run an applied revision).

## Rollback
Both migrations' `downgrade()` re-create the columns/tables and reverse-backfill
from the mapping tables (best-effort). `challonge_team` is recreated with an
IDENTITY id; `predictions` comes back empty (repopulated by the next v2 run —
but note Phase 1 removed the v1 writer, so predictions will only be fed by v2).

## Residual cleanup (independent, low priority)
- `tournament.map_veto_config.map_pool_ids` orphan column on prod (dbarch05
  normalized it to `map_veto_config_map` but the manual restore left the old
  column). Drop when convenient; nothing reads it.
