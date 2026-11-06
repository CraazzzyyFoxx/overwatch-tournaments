import type { TournamentStatus } from "@/types/tournament.types";

/**
 * The tournament status and the node lifecycles, mirrored from `backend/shared/core/enums.py` and
 * `backend/shared/core/flow_state.py`.
 *
 * The status is derived from the nodes, so the browser mirrors no tournament transition table: it only ranks the four
 * statuses and knows where an admin may move a node and which phases a node's schedule may carry.
 *
 * `lib/tournament/lifecycle.parity.test.ts` reads the Python modules and fails on drift; a hand-mirrored constant with
 * no such test is a rumour.
 */

/** The `TournamentStatus` values in enum order; later means later in the tournament's life. */
export const TOURNAMENT_PHASES = ["announcement", "live", "completed", "archived"] as const satisfies readonly TournamentStatus[];

const PHASE_RANK = Object.fromEntries(
  TOURNAMENT_PHASES.map((status, index) => [status, index])
) as Record<TournamentStatus, number>;

/** Position in the status order. Higher means later in the tournament's life. */
export function phaseRank(status: TournamentStatus): number {
  return PHASE_RANK[status];
}

/** Whether the tournament is at or past `target`. */
export function reachedAtLeast(status: TournamentStatus, target: TournamentStatus): boolean {
  return phaseRank(status) >= phaseRank(target);
}

/** `flow_state.SCHEDULE_PHASES`: the phases a node of each kind may carry a schedule row for. */
export const SCHEDULE_PHASES = {
  registration: ["open", "check_in"],
  formation: ["start"],
  stage: ["start"]
} as const satisfies Record<"registration" | "formation" | "stage", readonly string[]>;

/**
 * `flow_state._VALID_TRANSITIONS`: where an admin may move a node of each lifecycle kind. A stage's action menu offers
 * exactly `NODE_TRANSITIONS.stage[stage.status]`; each one is `POST /admin/flow-nodes/{node_id}/transition`.
 */
export const NODE_TRANSITIONS: Record<
  "registration" | "formation" | "stage",
  Record<string, readonly string[]>
> = {
  registration: {
    draft: ["open"],
    open: ["check_in", "closed"],
    check_in: ["closed"],
    closed: ["open"]
  },
  formation: {
    draft: ["forming"],
    forming: ["draft", "completed"],
    completed: ["forming"]
  },
  stage: {
    draft: ["ready"],
    ready: ["draft", "live"],
    live: ["completed"],
    completed: ["live"]
  }
};
