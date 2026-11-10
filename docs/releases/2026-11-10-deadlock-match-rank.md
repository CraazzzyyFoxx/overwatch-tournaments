# Deadlock match view: rank on the match date, build order: release note

**Rank on the match date.** Each player in a Deadlock match now shows the rank they held on the match date: the tier
emblem and the step's name (`Oracle 3`).

- **Backend:** `NativeMatchMember.rank_value` is new. It is filled through the new `DisciplineSpec.native_rank_at`
  hook, which only Deadlock implements (`shared/disciplines/deadlock/ranks.py: ranks_at`). For each of the player's
  Steam accounts it takes the newest `rank.rank_snapshot` row captured by the match's `played_at` (else `created_at`).
  It keeps ranked rows only and picks the best account. An account first polled after the match has no rank for it.
  The match-stats cache key moved to `native_match_stats:v4`.
- **Frontend:** the rank value resolves on the discipline's `native_ladder`, the same way rank history does.
  - Teams: the rank sits next to the player's name. It is hidden when unknown.
  - Full table: a "Rank" column follows the player column. It shows a dash when unknown.

**Build order.** Each shop column now lists tier 1 first and tier 4 last; items of the same tier stay in purchase
order. Before this change it was strongest first.

**Breakdown.** The "Players over time" series switch is only as wide as its options; it used to fill the row.
