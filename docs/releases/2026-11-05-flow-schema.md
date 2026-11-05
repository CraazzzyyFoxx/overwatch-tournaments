# Tournament flow schema: release note

Every tournament now has a flow graph: registration, team formation and stage nodes, plus filter and merge nodes between
stages, with the ranked results of each node. It is read-only. Nothing in the UI reads it yet, and nothing about
tournament status, stages, registration, the balancer or the draft changes.

## Wire changes

- New public route: `GET /api/v1/tournaments/{id}/flow`, subject `rpc.tournament.get_flow`. It returns the nodes with
  their resolved ports, the edges and every node's ranked results. A hidden tournament is visible only to its
  workspace's admins and users on its preview allowlist.
- New admin route: `GET /api/v1/admin/tournaments/{id}/flow`, subject `rpc.tournament.flow_get`. It needs the workspace
  `tournament.read` permission. It adds the validator's issues on the stored graph and the port catalogue per node kind.
- `gateway/internal/openapi/schemas.json` and `frontend/src/types/api.generated.ts` are regenerated (additions only).

## Known limits

- The legacy graphs are a snapshot until the next phase. Stage creation or deletion, stage flag flips and tournament
  status changes made after the migration do not move node statuses or add nodes. Results do stay current: the
  standings job recomputes them.
- Statuses are clamped to what the tournament's current state allows. An unfinished tournament whose playoff looks
  finished gets a `live` stage node instead of a `completed` one.
- Registration nodes list approved registrations only. Formation lists every team of the tournament, in team id order.

## Migration and deploy

- `flowP2_01_flow_tables` creates the four flow tables and the foreign key from `participant_result`.
  `flowP2_02_legacy_flows` builds the graph of every existing tournament and aborts on a status mismatch.
  Rehearse it on a production dump first.
- Deploy from one SHA in this order: migration, tournament-service, gateway, frontend.
- Then run `cd backend/tournament-service && uv run python recompute_flows.py` once. It prints one line per tournament,
  reports a failing tournament on stderr without stopping, and exits non-zero if any failed. Running it again is safe.
