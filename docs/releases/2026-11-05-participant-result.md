# Per-member tournament result: release note

A member who played for two teams in one tournament used to count twice (once per team) in placement counts, averages,
titles, streaks and rank history, and a member's "placement" was whatever team-grain `standing` row a read happened to
pick. One table now holds each member's result in each finished tournament, and every placement read goes through it.
Design: `docs/superpowers/specs/2026-11-05-tournament-flow-design.md` §4.7, §11.2–11.4.

## What changed

- **The table `tournament.participant_result`**: one row per `(tournament_id, workspace_member_id)` with `final_team_id`,
  `placement` (NULL when the final team never had a positive place), `field_size` (the tournament's team count) and
  `source_node_id` (always NULL for now). Every FK to `tournament.tournament` cascades on delete.
- **How a row is chosen** (rule 2): the last team the member played for (the latest non-substitute `player` row), and
  that team's positive `Standing.overall_position` in its last stage by `Stage.order`.
- **When it is written**: when a tournament becomes `completed` (`transition_status`), on any later standings
  correction of a completed tournament, and after a user merge for every tournament the merge moved rows in. The
  migration backfills every finished tournament (`is_finished`, archived included) with the same rule as frozen SQL.
- **What reads it**: the player profile (teams, placements), the users overview (sorts, average and best placement), the
  compare page, the `/statistics` titles (`_championships`), the analytics frame and read queries
  (`service.py`, `read_queries.py`), the shift evaluation (`evaluate.py`) and backtest (`backtest.py`), and the
  Overwatch achievement conditions `standing_position`, `standing_record`, `standing_count`, `reached_playoffs`,
  `tournament_winrate`, `consecutive`, `stable_streak`, `div_change`. Rank-history readers and single-row lookups pick
  the member's one tournament row: the final team's, then a non-substitute, then the highest id. Team-grain reads
  (standings pages, team results) still read `standing`. `mvp_dominance` now counts only the matches of the team the
  player's row belongs to.
- **Stored achievement rules** whose tree uses one of those leaves gain `tournament.participant_result` in
  `depends_on`. A tree that had `include_groups` on `standing_position` loses the param and gets `rule_version + 1`.

## Behaviour changes

- **One count per member per tournament.** A member whose non-final team won no longer counts a title, a top-N finish or
  a placement from that team; the final team decides.
- **Group-only tournaments get placements and champions.** A tournament with only group or round-robin stages used to
  have none for these reads; its final placement is the standing in its last stage, so its winners now count as
  champions and receive the "winner" grants.
- **A live tournament has no placement until it completes.** The profile, the draft card and compare show a
  tournament's placement only after `completed`; participation counts still include live tournaments.
- **`standing_position` loses `include_groups`.** A member's placement is the final one, not a group one. A rule bundle
  exported before this release that still carries `include_groups` is rejected on import (unknown param): remove the
  key from the bundle first.
- **`consecutive` metric `day_two`** (default `placement < 7`) now also passes for a team knocked out in groups and
  ranked 5th or 6th in a tournament with a playoff. No catalog rule uses it; only admin-authored rules change.
- **Roster edits after completion are not rewritten.** Removing a player of a finished tournament leaves a result whose
  `final_team_id` no longer joins, and the tournament drops from overview, compare and titles until the next standings
  correction or reopen.

## Rollout

The migration changes stored rules and backfills placements; it does not touch stored achievement grants or stored
analytics shifts. Until both are re-evaluated, old tournaments keep their old-rule results (a member whose non-final team
won keeps "winner" while the profile shows 0 titles). After `alembic upgrade head` (`make migrate`):

1. **Achievements, per workspace and discipline.** Call `POST /api/v1/admin/ws/{workspace_id}/achievements/rules/evaluate`
   (RPC `rpc.stats.ach.evaluate`, permission workspace `achievement.update`; the admin UI's Run evaluation button calls
   the same endpoint for one rule) with the body `{"discipline": "overwatch"}`. Leave out `tournament_id` and `rule_ids`:
   the run covers every enabled rule over every tournament of the workspace. Repeat for every workspace that has
   Overwatch tournaments. The run is diffed against the stored results, so it **revokes** grants the new rules no
   longer give as well as granting new ones; manual grants and revokes stay. On a workspace that is not verified, the run
   is queued (`status: queued`) and drained by the deferred consumer; follow it on
   `GET /api/v1/admin/ws/{workspace_id}/achievements/rules/runs`.
2. **Analytics, per workspace that has members on two teams in one tournament.** Follow
   `backend/analytics-service/docs/runbook-shift-recompute.md`, "Recompute on the prod host", without retraining: the
   v1 Points/Linear/OpenSkill recompute (step 2, `POST /v2/jobs` with `{"kind":"compute","tournament_id":<earliest
   tournament>}`) and the shift backfill (step 1b, `python -m src.services.ml.cli backfill --from <day> --to <today>`,
   run in the `analytics-worker` container). Stored `analytics.player_shift` rows computed under the old team-grain
   placement stay until then. The manual shift (`AnalyticsPlayer.shift`) is never touched.

Tell affected players: step 1 can remove grants.

## Not in this release

- The leaderboard sink and flow-based formation ordering (`formation_node`) write the same table in later phases;
  `source_node_id` has no FK until then.
- `is_league` filters are unchanged.
