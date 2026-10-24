# Tournament analytics: shifts with uncertainty, leak-free features, an honest forecast: release note

The division forecast now shows a climb or drop only when the algorithm is at least 80% sure, every stored shift
carries its uncertainty, and the inputs no longer contain the results they are meant to predict.

Why: an audit of the shift algorithms found that the forecast called moves on noise, and that several inputs were wrong.
- **Noise.** In a simulated field where every player is rated right and every map is a coin flip, Linear forecast a move
  for 39% of players after one tournament and Points for 33% after ten.
- **Double counting.** Linear kept recommending a promotion right after the organizers had applied it.
- **Leaks.** Performance v2's "pre-encounter" team strength already contained the encounter's result, and its logless
  fallback read the score it was predicting.
- **Order.** Histories were ordered by tournament id, which is not chronological.
- **Stale caches.** Cached feature frames survived a recalculation.
- **Validation.** The backtest compared the ML shift with the organizers' manual override.

## Backend

### Forecast and storage
* **Probability-gated forecast** (`src/domain/forecast.py`).
  - The mis-rating is taken as N(`shift`, `shift_sd`²) in canonical divisions.
  - The forecast shows the largest move k ≤ 3 with P(m ≥ k − 0.5) ≥ `FORECAST_CONFIDENCE_THRESHOLD` (default 0.8), then a drop by the same rule, otherwise hold.
  - `confidence` is now the probability of the shown outcome; for hold it is P(−0.5 < m < 0.5).
  - Half-divisions round away from zero. The old |shift| < 1 dead zone and banker's rounding are gone.
  - The move is applied on the canonical ladder and mapped back to the nearest tier of the tournament's grid, so it never leaves the grid.
* **Stored uncertainty.** `analytics.shifts.shift_sd` replaces the 0..1 heuristic `confidence` (migration `anlsd01`). NULL means unknown — a legacy row or an unranked player — and the forecast holds.

### Algorithms
* **Linear.**
  - A player's history restarts at their latest division change.
  - A tournament weighs maps/(maps + 4); without recorded maps it uses the match count.
  - Newcomers are no longer down-weighted.
  - `shift_sd` = 6.25·s/√(1.5 + evidence), where s is the map-weighted noise of the raw signal across the workspace.
  - A team without a standing no longer reads as a +3 placement.
* **Points.** The formula is unchanged. `shift_sd` = √(Σ coef²·maps) over the window the shift accumulates.
* **OpenSkill**, a new visible algorithm:
  - It uses the existing encounter-level Plackett–Luce replay over the 10 most recent tournaments by start date.
  - `shift` = current division − the division of μ.
  - `shift_sd` = σ in canonical divisions.
* **OpenSkill + ML.**
  - Without an MVP lift, a negative `local_zscore` now lowers the shift.
  - The MVP lift, and the smurf flag's MVP rule, need ≥ 5 logged matches.
  - `shift_sd` combines the Linear and OpenSkill sds with the individual term's per-match error.
  - `predict_with_uncertainty` replaces `predict_with_confidence`.
* **Performance v2.**
  - The pre-encounter strength replays the window from seed ratings and applies each encounter once. Before, two equal teams read 2027 vs 1973 before they had played.
  - `won`, `home_score`, `away_score` and `score_delta` are no longer coarse-fallback features.
  - Confidence uses the target's real span (1 − band/2), and coarse-only rows get 0.

### Pipeline
* **Chronology.** Points, Linear, the OpenSkill window, the shift-v2 rank history, the player-profile window, drift, the backtest's realised move and its latest tournament all order by `(coalesce(start_date, created_at), id)`.
* **Cascade.** Recalculating a tournament also rewrites the Points/Linear/OpenSkill rows of every later tournament of its workspace that already has them. The whole recalculation is one transaction with one commit.
* **Cache.** A compute job rebuilds every feature frame it reads (`refreshing_feature_cache()`), so a recalculation after a results correction sees the correction. `FEATURE_VERSION` is v1.6.

### Evaluation
* **`cli evaluate`** (new, read-only) scores every method on the encounters of each player's next tournament.
  - A player's level is the canonical division at the previous tournament minus the stored shift.
  - Baselines: `organizer` (the next tournament's ranks) and `no_moves`.
  - The report gives log-loss, Brier, AUC, coverage and the fitted scale k.
* **`backtest`** runs inside a transaction it rolls back, with fold artifacts in a removed temporary directory.
  - It scores the shift model against real baselines: no move, Points, Linear and OpenSkill.
  - Its realised-move metrics are labelled as agreement with organizer moves.

### API
* **Manual shift** (`rpc.analytics.shift`): updates only `AnalyticsPlayer.shift`, answers `{player_id, shift}`, and returns 404 without a row. Before, it joined an arbitrary algorithm's row and raised `TypeError` when none existed.
* **Team row.** `total_shift` = the sum of the players' forecast moves (tournament-grid divisions, up positive). `balancer_shift` = the team's mean canonical division minus the field's. `manual_shift` = Σ`shift_one`/100.

## Frontend

* Move 1/2 show divisions (they were ×100) and are typed `number | null`.
* Impact is shown only from a readable Performance v2 row. It is no longer derived from the shift, and a "why" line cites impact only when the score agrees with it.
* Algorithm order: Linear, Points, OpenSkill, OpenSkill + ML. The default choice is unchanged.
* Copy in en and ru:
  - analytics run when a tournament completes or an organizer recalculates, not after every map;
  - the manual shift is the organizer's override;
  - confidence is the probability of the shown forecast;
  - a hold reads "Predicted to hold".

## Contract

* DB: `analytics.shifts` +`shift_sd` (nullable) −`confidence` (`anlsd01`; the downgrade restores `confidence`).
* `PlayerShiftUpdate` is the `rpc.analytics.shift` response. The request carries no `team_id`.
* Setting `FORECAST_CONFIDENCE_THRESHOLD` (read time).
* `run_rolling_backtest(connection, …)` takes an `AsyncConnection`. Report keys `agreement_with_organizer_moves.*` and `calibration_vs_organizer_moves` replace the v1/v2 keys.
* Artifact conversion receipts record only `y_hat` for performance wrappers and nothing for shift wrappers.

## Removed

`get_linear_hybrid_shift_lookup`, `score_history`'s hybrid path, `lookback_start_tournament_id` and `get_matches` (id-interval windows), the backtest's manual-override "v1" baseline, `deriveImpact`, the Linear newcomer weight and the heuristic shift `confidence`.

## Rollout

Follow `backend/analytics-service/docs/runbook-shift-recompute.md`:
1. `make migrate`.
2. Retrain Performance v2 and the shift model, then backfill.
3. Run one compute job for the workspace's earliest tournament; the cascade refreshes the later ones.
4. Run `cli evaluate` to choose the default algorithm.

Until the recompute, stored rows have no `shift_sd`, so every forecast holds.

## Known limits

* **Points' sd.** It is map noise without a prior, so a short history reads too certain: a single 7–1 shows "promote 1 (83%)". In the simulated field Points still shows a move for 10–19% of players.
* **Hand-set constants.** `LINEAR_SHIFT_SCALE` and the ML blend constants are still set by hand; `evaluate` is the tool to tune them.
* **Downgrade.** The migration's downgrade was rendered offline, not executed.

## Verification

* **analytics-service suite** against the local test Postgres: 340 passed.
  - The one failure in the first run was a test pinning the realised-move SQL `ORDER BY`. The order now lives in pandas and is covered behaviourally, so the pin was removed.
* **Backend boundary/discipline tests:** 104 passed.
* **Lint and checks:**
  - `ruff check` and `ruff format --check` on the changed files;
  - `lint-imports` for analytics-service and the backend workspace;
  - `export_erd.py --check`, `check_rpc_docs.py`, `export_openapi_schemas.sh --check`;
  - `alembic heads` shows the single head `anlsd01`.
* **Frontend:** `tsc --noEmit` clean; `vitest run` on analytics, i18n and services: 25 files, 144 tests; `eslint` clean; `lint:zones` clean. `lint:design` has 2 findings, both in `DivisionRangePicker.tsx`, which this change does not touch.
* **Smoke on the real code:**
  - Equal teams read 2000/2000 before their first encounter.
  - After a +2 promotion and 4–4 play, Linear reads +0.11 (hold) instead of +1.45 (promote).
  - In the null field, the share of players shown a move:

    | Algorithm | Before (after 1 / 10 tournaments) | After (after 1 / 10 tournaments) |
    |---|---|---|
    | Linear | 39% / 15% | 0% / 3% |
    | Points | 12% / 33% | 10.5% / 19% |
