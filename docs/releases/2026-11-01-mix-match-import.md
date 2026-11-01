# Mix match import by external id: release note

A recorded mix match of a game with a match fetcher (`capabilities.match_fetch`, Deadlock today) can now be filed by
its id in the game's own records. The stats worker fetches it like a tournament game's import and ingests it as the
match's statistics, shown only inside the mix. The recorded result is never touched.

**Routes** (stats-service; `match_id` is the mix match's encounter):

| Route | Subject |
| --- | --- |
| `POST /api/v1/custom-games/{custom_game_id}/matches/{match_id}/match-import`, body `{external_id}` | `rpc.stats.ingest.mix_fetch` |
| `GET` on the same path: the match's requests, newest first, with the organizer warnings | `rpc.stats.ingest.mix_fetch_list` |

- Gate: the mix log upload's audience. That is the mix's host, a co-host or a superuser, or workspace `log.create`.
  Closed mixes are included. A match of another mix answers 404.
- Same request semantics as the tournament import. It is idempotent per `(external_id, game)`. A failed request
  resets to pending. One match id serves one game of a workspace (409 `match_already_imported`). Another id for the
  same match replaces its statistics. 422 `invalid_external_id` / `unsupported_ingestor`.
- `MatchImportInput`, `MatchImportRead` and `MatchImportWarningRead` moved to `shared/schemas/match_import.py`. The
  manifest names them both as `tournament.*` and as `stats.*`.

**Worker.**
- A mix request carries `hint_tournament_id = NULL`. Its bytes are stored under `logs/mix/{custom_game_id}/{hash}`,
  and the ingest job carries the match's encounter and game hints. Ingest stays statistics-only for a mix.
- A workspace's match that is already stored reuses its job, whatever the source answers now: deadlock-api enriches a
  match after demo analysis, and the same id with other bytes used to fail with `idempotency_conflict`.
- A job left without a `stats.match` is re-pointed at the request's game and re-pended. That covers DONE after a mix
  Undo or Cancel cascaded the match away, FAILED and AWAITING_LINK, under the same tournament hint (NULL = NULL for a
  mix). Undo deletes the match's requests with it, so filing the same id for the re-recorded match works. This is the
  upload's revive (`LogRecordsService.revive_orphan`, shared now).
- `participants_dropped` compares each team's observed players with the mix match's active seats. A mix has no
  tournament format to read starters from.

**Reading.** `rpc.balancer.custom.match_history` rows read `log_state` from the newest ingest job and also from the
newest `stats.match_fetch` of the match: a pending import is `processing`, a failed one is `failed`, and `processing`
wins.

**Frontend.** Each mix history row has an «Загрузить статистику по ID матча» button for the log upload's audience,
when the mix's game has `capabilities.match_fetch`. It opens `MatchImport` with a mix scope: the id form, the filed
ids with status, attempts, `last_error` and warnings, and 30 s polling while one is pending.

## Migration and deploy

One migration after `mixstatsmv01`: **`mixfetch01`**. It makes `stats.match_fetch.hint_tournament_id` nullable and
adds `ix_match_fetch_encounter`. Deploy from one SHA: run the migration, then roll stats-service (+ worker),
tournament-service, balancer-service, the gateway (route table, regenerated `schemas.json`) and the frontend.

Without `DEADLOCK_API_KEY`, deadlock-api serves a match not yet in its cache from Steam at 3 requests per hour per
IP. The worker's backoff absorbs that within the 24 h window, but set the key where mixes import often.

### Downgrade cost

Downgrade deletes the mix requests (`hint_tournament_id IS NULL`) before restoring NOT NULL. Their ingest jobs and
statistics stay.

## Wire changes

| Change | Kind |
| --- | --- |
| `POST`/`GET /api/v1/custom-games/{custom_game_id}/matches/{match_id}/match-import` | new routes |
| `stats.MatchImportInput`, `stats.MatchImportRead`, `stats.MatchImportWarningRead` | additive |
| Mix match history `log_state` also reflects the newest match import | changed meaning |
