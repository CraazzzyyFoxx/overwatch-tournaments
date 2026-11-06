# League merge: one tournament per league season: release note

The league concept goes away (spec §11.5, §15). Every historical league season, its day tournaments, is merged into one
tournament with the existing flow tools, and `tournament.is_league` is dropped.

**What the merge does** (`python -m scripts.league_merge`, not an Alembic migration), per league season, in one
transaction:
- Target = the earliest day (keeps its id and slug), renamed to the league name; `end_date` becomes the latest day's end.
- Every day keeps its own branch `registration → formation → stage(s)`, renamed `Day N` / `Day N · Teams` /
  `Day N · <stage>` (with `· <division>` when the mapping names one) and stacked on y; `Stage.order` is offset per day.
- The day sinks feed an `aggregate` node (the owner's formula from `league_merge.json`, R3.Q5) and a `leaderboard`
  `Table`; the flow is recomputed and `participant_result` rewritten, so the season table is the tournament's result.
- Every tournament-keyed row is re-pointed to the target (composite FKs deferred, `flowP6_01`). Collisions:
  a member keeps the latest day's registration profile and every day's participation becomes an entry of that day's
  registration node; forms collapse into the latest with every version kept; same-name registered teams collapse into the
  latest; `discord_channel`, `encounter_report_form`, `roster.team_format`, `google_sheet_feed`, `voice_settings`
  keep the latest day's row; `stream.session`, `challonge_source`, `tournament_link`, `pick_ban_config`,
  `tournament_preview_access`, `voice_channel` drop key duplicates; `recalculation_state`, `computation_job` and
  `participant_result` of the days are recreated. Dropped rows are logged.
- The emptied day tournaments are deleted (no slug or id redirects).
- Afterwards (also for the leagues that merged before a later one failed): user-cache generation bumped, one evaluation
  run per affected workspace, then one analytics `compute` job per verified workspace queued; `grant` writes an
  `AchievementOverride(grant, "league merge")` for every achievement result that disappeared (evaluation results of a
  tournament earned on several days cannot be re-pointed). `achievements.rule.min_tournament_id` cutoffs on a merged
  day move to the target (the season start).

**Removed everywhere:** the `is_league` column and field, the `is_league`/`include_league` condition params (stored
ones are stripped by `flowP6_02`), `TournamentFacets.league`/`.standard`, the league filters and badges of the frontend.
`tournament_type` stays as a parameterless "played the tournament" condition.

## Delivery

One PR, migrations `flowP6_01_deferrable_fks` → … → `flowP6_02_drop_is_league` (chained on the current head). Production
order, run by the owner from the release SHA:

1. Against production: `uv run alembic upgrade flowP6_01_deferrable_fks` (the deployed services keep running; the FKs
   only became deferrable).
2. `python -m scripts.league_merge plan` (each season is named `<league> · Season N`; rename it) → the owner fills every
   `aggregate` → `apply --dry-run` → `apply` → wait for the queued evaluation runs → `grant --granted-by <auth user id>`.
   Keep `league_merge.json` and `league_merge.snapshot.json` outside the container filesystem (a mounted path, or
   `docker cp` them out right after `apply`). `apply` never overwrites an existing snapshot (it extends it), so after a
   failure fix the cause, drop the merged leagues from the mapping and run `apply` again; `grant` refuses a snapshot
   with no evaluation run. If `apply` prints `skipped: job N active` for a workspace, queue an analytics `compute`
   job from its earliest target once that job finishes.
3. Normal deploy (`alembic upgrade head` passes the `flowP6_02` guard because no league row remains).

A deploy started before step 2 stops at `flowP6_02` with "N league tournaments remain" and changes nothing past the
revisions before it. On a database without leagues (CI, fresh installs) the PR deploys alone. Rehearse on a restored
dump first: `make backup-restore-local DUMP=<object>` (`docs/backup-rustfs.md`).

## Wire changes

| Change | Kind |
| --- | --- |
| `is_league` on tournament reads and writes, user and achievement reads | removed |
| `is_league` query param of `GET /api/v1/tournaments`, `/tournaments/lookup`, `/tournaments/facets` | removed |
| `TournamentFacets.league`, `TournamentFacets.standard` | removed |
| Achievement condition params `is_league`, `include_league` (stored ones stripped) | removed |
| League tournaments count in every statistic and achievement | changed behavior |
| User profile tournament history lists a tournament once (the member's final team, placement from `participant_result`) | changed behavior |
