# Balancer pool and flow-step guidance: release note

A balance run could seat fewer players than the balancer pool showed (tournament 124: 44 of 50, so 8 teams and 4
left over instead of 10). Exporting teams and starting a stage also failed with errors organizers could not act on
(`Formation node 577 is 'draft', not forming`). Both are fixed.

## What changed

- **Balancer pool reads registrations live.** `shared.services.flow_queries.input_member_ids` now reads a registration
  node's `participants` output straight from its entries (`registration_output_rows`) instead of the stored
  `flow_node_result` rows. A check-in, approval or balancer-status change does not recompute the flow, so the stored
  rows went stale and the balance job, the draft pool and the individual-Swiss pool dropped players. The flow engine
  writes its rows through the same query.
- **Flow refusals are translated everywhere.** The global error toast maps known `errors.flow.*` codes to their
  translated, actionable text; the server's English `msg` no longer reaches organizers. The export dialog, the node
  controls and the stage lifecycle actions show their own message once instead of twice.
- **Refusals list every missing step.** When a move is refused (`input_not_final`, `formation_not_forming`…), the
  message lists all the moves it waits on, in the order the server enforces (`lib/tournament/flow-path.stepsTo`, a
  mirror of `FlowNodeService._assert_inputs_final`; `FINAL_STATUSES` is parity-tested against `flow_state.py`).
- **Export moves the flow for you.** *Export to tournament* on the balancer first lists the moves it needs (close the
  registration, start forming), runs them after one confirmation, then exports. It stops at the export: completing the
  formation and starting a stage stay separate steps.
- **Tournament steps panel** on the balancer (in place of the node controls) and above the bracket's stage editor: the
  registration → formation → stage chain with each node's status, the planned moves and a *Next step* button (one
  confirmation per move). It does not offer to complete a live stage (standings do that) or a formation before its
  teams are exported.

## Rollout

Deploy the backend (balancer-service and tournament-service share `backend/shared`) and the frontend. No migration.
Stored registration rows refresh on the next flow recompute; nothing reads them for the pool any more.
