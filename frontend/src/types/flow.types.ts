import type { Schema } from "@/types/api";

/** A tournament's flow graph: nodes with their ports, edges and every node's ranked results. */
export type FlowRead = Schema<"tournament.FlowRead">;

type FlowNodeUpsert = Schema<"tournament.FlowNodeUpsert">;

/**
 * A partial graph edit for `PUT /admin/tournaments/{id}/flow`: node/edge upserts and deletes. A node upsert names its
 * `kind` and `name`; every other field (`ref`, `stage_id`, position) may be left out.
 */
export type FlowChanges = Omit<Schema<"tournament.FlowChanges">, "nodes"> & {
  nodes?: (Pick<FlowNodeUpsert, "kind" | "name"> & Partial<FlowNodeUpsert>)[];
};

export type FlowNodeRead = Schema<"tournament.FlowNodeRead">;

/** Lifecycle status of a node; which values apply depends on its kind. */
export type FlowNodeStatus = `${Schema<"tournament.FlowNodeStatus">}`;

/** One phase window (`open`, `check_in`, `start`) of a node. */
export type FlowNodeScheduleEntry = Schema<"tournament.FlowNodeScheduleEntry">;

/** A registration, formation, stage or leaderboard node as `TournamentRead.flow_nodes` carries it. */
export type TournamentFlowNode = Schema<"tournament.TournamentFlowNodeRead">;
