# Flow transition nodes: release note

Advancement between stages now lives in flow nodes (`filter`, `merge`, `split`, `aggregate`, `leaderboard`). A stage is
seated from the result rows of the node wired into its `participants` port when it turns `ready`; the stage and group
advance counts, the TENTATIVE seats and the wire-from-groups routes are gone.

## Deploy order (required)

`flowP4_01_source_result` copies the legacy wiring into the flow and aborts, listing the input ids, when a wired FINAL
seat has no flow result row. No migration fills `flow_node_result`; only `recompute_flows.py` does. So, from the release
SHA, against production:

1. `uv run alembic upgrade flowP3_06`
2. `cd backend/tournament-service && uv run python recompute_flows.py` (idempotent; non-zero exit when a tournament
   failed: fix it and re-run before going on).
3. `uv run alembic upgrade head`. When leagues still exist, stop at `flowP6_01_deferrable_fks` and run the league merge
   first, see [`2026-11-05-flow-p6-league-merge.md`](./2026-11-05-flow-p6-league-merge.md): `flowP6_02` refuses to run
   while a league tournament remains.

The chain is `flowP3_06 → flowP4_01 → flowP6_01 → flowP4_02 → flowP6_02 → flowP4_03`. Rehearse on a restored dump first
(`make backup-restore-local DUMP=<object>`): `flowP4_01` also aborts on legacy drift, for example an `advance_count`
edited after wiring so that the filter no longer holds a seated team.

| Revision | What it does |
| --- | --- |
| `flowP4_01_source_result` | `stage_item_input.source_result_id` replaces `source_stage_item_id` / `source_position` (backfilled); the double-elimination split moves into the legacy filters; TENTATIVE inputs become EMPTY; `seed_ranking` accepts `source`, `cross`, `snake` |
| `flowP4_02_drop_advance` | drops `advance_count` / `advance_upper_count` of stages and stage items (the counts were copied into the filters by `flowP4_01`; not restored on downgrade) |
| `flowP4_03_seat_source` | `stage_item_input.seat_source` (`flow` / `manual`; a seat with a team and no source row becomes `manual`); completed stage nodes without `completed_at` get the time of their latest encounter |

## Removed

- Routes `POST /api/v1/admin/stages/{id}/wire-from-groups` and `POST /api/v1/admin/stages/{id}/auto-wire`, subjects
  `rpc.tournament.stage_wire` and `rpc.tournament.stage_auto_wire`, and the `WireFromGroupsRequest` schema. Wire a stage
  through a `filter` node in the Flow tab instead.
- `advance_count` / `advance_upper_count` on stage and stage item reads, creates and updates (the cut line of the public
  standings table goes with them).
- `source_stage_item_id` / `source_position` on stage item inputs (reads and writes), replaced by `source_result_id` on
  reads; the TENTATIVE input type (EMPTY now).
- Added: `seed_ranking` accepts `source`, `cross`, `snake`.

## Behaviour changes

- `draft → ready` seats the stage from its input rows by `seed_ranking` and refuses when the input is not final
  (`input_not_final`) or a tie straddles a filter's cut (`boundary_tie`; pin the tied team first).
  - Seats an admin wrote (seed-teams, slot edits, moves) are `manual` and kept; an input team they do not hold is seated
    into an empty slot by the stage's seeding rule (409 `not_enough_slots` when none is free). A manual seat of a team
    outside the input is refused (`seed_not_in_input`).
- A result change upstream of a `ready` stage re-seats its `flow` seats (a departed team is replaced in place); `manual`
  seats never move. Once a stage is `live`, or a formation downstream left `draft`, corrections that would change what it
  consumed are refused (`downstream_started`); a pin on a group place that a started node already took is refused above
  the cut.
- The aggregate and the leaderboard score teams that tie on a place (two semi-final losers) with the same place, and a
  seeded team that never played ranks last. Inputs without `completed_at` (legacy stages, merged days) are ordered by
  their latest encounter, then by edge order.
- A leaderboard sink writes `participant_result` (rule 1) with those shared places.

## Known limits

- A stage reverted to `draft` that already has encounters is re-seated in place on the next `draft → ready`: it can swap
  teams but not grow or shrink.
- `ready → live` does not re-check the input.
