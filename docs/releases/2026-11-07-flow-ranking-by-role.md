# Ranking by role and the season table: release note

A league season of balanced teams counted every day a player played into one total, whichever role they played: a
player who tanked on two days and supported on two others had all four days compete for the same best-K slots. The
aggregate node can now rank every top-level role on its own, and the public season table became a working table.

## What changed

- **`tournament.flow_node_result.role`** (migration `flowP8_01_result_role`): the top-level role code of a by-role
  ranking row, NULL everywhere else. The member uniqueness index becomes `(node_id, port, workspace_member_id, role)
  NULLS NOT DISTINCT`, so every role-less port keeps one row per member.
- **`AggregateNodeConfig.by_role`** (default `false`, players unit only, `aggregate_by_role_unit` otherwise): one ranking
  per role. A day's role is the player's roster role in that day's team (`Player.role`), or the frozen
  `PlayerStanding.role` of an individual Swiss day; a roster row without a role ranks under `role: null`. `rank` and
  `tie_group` count inside the role.
- **Breakdown entries** of every aggregate carry `role`, `team_id` and the input row's `wins`, `draws`, `losses`,
  `map_diff`, `buchholz`, `ffa_score`, by-role or not. Rows written before this release keep the old four keys until
  the next recompute.
- **Validation**: a by-role aggregate may feed only a leaderboard (`aggregate_by_role_target`).
- **Leaderboard pins** gain `role`: with a by-role ranking a pin places `(participant, role)` inside that role.
- **`participant_result`** for a by-role leaderboard sink: each member's best place over their roles, `field_size` the
  row count of that role.
- **Public Table tab**: role tabs for a by-role ranking (a role column otherwise), search by name, sortable columns,
  sticky place and name columns, the day's place and a counted mark in each cell, a tooltip with team, role, W–D–L and
  Buchholz, and the role, search and sort in the URL.

## Rollout

1. `alembic upgrade head` (`make migrate`) before the new services start: the engine writes `role`.
2. Turn the ranking on per season: admin → tournament → **Flow** → the season's **Aggregate** node → **Ranking by role**
   → **Save flow**. The save recomputes the flow; a finished tournament's `participant_result` is rewritten with it. An
   aggregate that feeds only a leaderboard is never frozen, so a completed season can be switched.
3. Seasons left as they are change only in their breakdown entries (filled on the next recompute, or at once with
   `python recompute_flows.py` in tournament-service).

Downgrade deletes the by-role rows before restoring the old index; switch `by_role` off and save to rebuild them as one
ranking.
