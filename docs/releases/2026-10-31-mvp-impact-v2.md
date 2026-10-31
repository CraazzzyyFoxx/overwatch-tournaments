# Overwatch MVP: impact_v2 — one MVP, hero-fair, explained: release note

The map MVP is now one number everywhere — the place a player sees, the analytics that move ratings, the achievements
and the statistics all read `impact_rank` — and it no longer rewards a hero pick, a role or a short stint.

Why: the review of `impact_v1` found that the system ran two MVPs side by side and that the newer one was biased.
- **Two MVPs.** The profile showed `impact_rank`, but the Shift v2 lift, the smurf flag, `match_mvp_check` and every
  `COALESCE(ImpactRank, Performance)` read still used the legacy `performance` rank (raw totals, damage = healing 1:1).
- **Hero bias.** Rates were compared with the role's mean, so a hero with an unusual stat line scored before the match
  started (a damage hero's healing, a support's blocked damage).
- **Kills counted many times.** Nine correlated kill stats held 54% of the hand-picked weight; healing held 4%.
- **Fake places.** Flex players, short stints and players without baselines scored 0 and still took a mid-table place.
- **Noise.** Round places used whole-map baselines on 90-second rounds; there was no shrinkage for short playtime.
- **Rank axis.** Overperformance bucketed a role-agnostic roster rank into global terciles mixing workspace grids.

Design: `docs/superpowers/specs/2026-10-31-mvp-impact-v2-design.md` (decisions R1–R4 of the 2026-10-31 session).

## Backend

### Formula (`shared/disciplines/overwatch/impact.py`, constants `shared/core/impact.py`)
* Scored per **hero stint**: per-10-minute rate → winsorised z against the hero's baseline (≥ 30 stints) or the role's.
* Kill-feed stats are attributed to the hero: first picks, ultimate and support kills to the killer's, first deaths to
  the victim's.
* Per-role weights (`shared/core/impact_weights.py`, fitted offline) over 20 features: v1's 17 plus damage taken,
  barrier damage and ultimates earned. Each role's composite is standardised, so the MVP chance per slot is role-neutral.
* Quality = time-weighted stint mean; `impact_points` = quality × `M/(M + 3 min)` × time share.
* `impact_rank` = competition rank (ties share a place) over scored players only. Under 60 s of classed play, or no
  baselines: no impact facts, no place.
* `overperformance_score` compares quality with the expectation for the player's dominant role and rank quintile: the
  rank for the role actually played, among the players of that role in the same tournament or mix.
* New facts: `overperformance_badge` (1 for the map's top overperformer past the baseline's 95th percentile, 0 for the
  rest who have one) and 20 `contrib_*` per-feature contributions (map only, stat group `impact`).

### Baselines and storage
* `stats.stat_baseline.entity_id` (hero) with `uq_stat_baseline` over `(formula_version, role_id, rank_bucket, stat_id,
  entity_id)` NULLS NOT DISTINCT. Rows: role and hero feature baselines, the role scale, the quintile expectation and
  its role fallback; `meta` carries `n`, `badge_threshold`, `window_days`, `max_matches`.
* Built from the most recent ≤ 5000 maps of the last 365 days. Recompute refuses to run while
  `impact_weights.FITTED` is false and never wipes on zero rows.
* `rank_quintiles.py`: tournament ranks from `registration.role.rank_value` (else the roster rank), mix ranks from the
  seat; a role's population is the members playing that role; fewer than 5 ⇒ no quintile.

### Legacy MVP removed
* `performance` and `performance_points` are no longer computed (decoder, `derive_match`) and their facts are deleted
  by `impactv201`. `LogStatsName.Performance`/`PerformancePoints` and the projected stat_defs go.
* Every `COALESCE(ImpactRank, Performance)` read now reads `impact_rank` only: tournament leaderboards and per-user
  MVP stat, avg MVP, MVP maps, the `mvp1` filter, compare, teammates, the hero-compare whitelist.
* `BoundParticipant.rank` is gone (the baselines no longer bucket on the seat rank).

### Analytics
* `mvp_dominance` (smurf flag, Shift v2 lift) reads `impact_rank`; the lobby is the players with a rank.
* The throw detector's round residual reads per-round `impact_points`; v1 log coverage reads `impact_points`.
* `performance`/`performance_points` left the feature frames (no trained artifact used them).

### Achievements
* `match_mvp_check` defaults to `impact_rank`; `impactv202` rewrites stored rules from `Performance` to `ImpactRank`
  and disables rules naming `PerformancePoints` (no comparable target).

### Tools
* `stats-service/fit_impact_weights.py`: read-only, bounded (`--max-maps`, default 3000; statement timeout) fit of the
  per-role weights — ridge logistic regression on decisive map wins, shrunk towards the v1 weights; λ is the smallest
  grid value that keeps every v1 weight's sign — gated on a 20% time-ordered holdout. `--write` rewrites
  `impact_weights.py` only when every check passes: team AUC(v2) ≥ AUC(v1), MVP share per role within ±5 pp of its
  slot share, hero bias ≤ 0.05 σ in-sample and, on the holdout, below that of role-only baselines.

## Frontend

* Placement reads `impact_rank` only (profile chip, match table, avg MVP); the series placement is the competition
  rank of the playtime-weighted mean map `impact_points` (the client `PerformancePoints` formula is gone).
* MVP tooltip: place; top 3 positive and top 2 negative contributions; "Above expectations" (bold with the badge).
  "Old rank"/"New rank" are gone. The badge reads the stored fact.
* The tournament stat boards, lobby tiles and teammates read the `impact_rank` key; group `impact` stats stay out of
  compare and the overview tiles. Admin achievements offer `ImpactRank` instead of `Performance`.

## Contract

* DB: `impactv201` (baseline schema, delete `impact_v1` baselines and legacy facts), `impactv202` (rule rewrite).
* API: the MVP placement key is `impact_rank` (was `performance`) in tournament stat maps, player-stats boards, the
  user tournament leaderboard `stat` and best-teammates `stats`; `LogStatsName` −2 +21 codes; Overwatch
  `member_totals` is empty. Regenerated `gateway/internal/openapi/schemas.json` and `api.generated.ts`.
* Read-cache keys bumped where the payload changed.

## Rollout

1. The weights in this release were fitted on the dev snapshot (`owt_dev`, 2,956 decisive maps since 2024-10-31; see
   the docstring of `shared/core/impact_weights.py`). Refit against production before its rollout:
   `cd backend/stats-service && uv run python fit_impact_weights.py --since-days 730 --write` (read-only, ≤ 3000 maps).
2. `make migrate` (`impactv201`, `impactv202`).
3. `rpc.stats.impact.recompute_baselines`, then `uv run python backfill_impact.py`.
4. Re-evaluate achievements per workspace; manual grants stay.
5. Retrain Performance v2 / Shift v2 (`backend/analytics-service/docs/runbook-shift-recompute.md`); the new artifacts
   apply to active and future tournaments only.

Until step 3, newly ingested maps get no impact facts (no baselines for `impact_v2`).

## Known limits

* **Fitted on the dev snapshot.** Production was unreachable from the development machine; the committed weights come
  from `owt_dev` (holdout AUC 0.9720 vs v1 0.9694; MVP share tank/damage/support 19.1/38.0/42.9% vs slots
  19.9/39.8/40.2%; hero bias in-sample 0.013 σ, holdout max 0.42 σ vs 0.65 σ role-only). Refit on production first.
* **Meta drift.** A frozen baseline cannot anticipate a balance patch: three damage heroes drift 0.39–0.46 σ on the
  newest maps. After a major patch, bump `FORMULA_VERSION`, refit, recompute and backfill.
* **Map outcome only.** Round winners are not stored, so the fit learns from map wins; Push/Clash (0:0) are excluded.
* **Frozen parity proofs** no longer compare the MVP surface (the legacy reference cannot produce v2); its numbers are
  pinned by the pure-core tests and the derive/backfill agreement test.

## Verification

* **Pure core and pipeline (DB-free):** `test_overwatch_impact_scoring` (20), baseline rows, derivation, backfill,
  rank quintiles, disciplines, decoder parity, constants, fit script — 94 passed.
* **Test Postgres, one file at a time:** derived parity (incl. role-scoped quintile populations), derive/backfill
  agreement, ingest binding, condition parity, cross-game reads, user read caches, user routes (11 passed, 62 skipped
  for want of a seeded dev catalog), stats and tournament reader parity (16, 21), analytics feature/prediction parity
  and v1/ML signal suites. `test_user_impact.py` needs a dev DB with a seeded map catalog and was not runnable here.
* **Smoke:** the fixture Workshop log decodes with no legacy facts; `derive_match` ranks only scored players, leaves the
  event-only participant without facts, carries only points/rank/overperformance on rounds; synthetic fits recover a
  planted signal (AUC 0.82 → 0.87) and pass the gates.
* **Fit on `owt_dev`:** λ chosen by validation log-loss (λ=1) failed every gate and flipped signs; the sign-preserving
  rule (λ=300) passes all four.
* **Checks:** `alembic heads` → `impactv202`; `check_rpc_docs.py`; `export_openapi_schemas.sh`, `export_erd.py`;
  `check_discipline_literals.py` clean; `lint-imports` (workspace + services); `ruff check`/`format`;
  `tsc --noEmit`; `eslint` on changed files; `lint:zones`.
