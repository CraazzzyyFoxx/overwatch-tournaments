import type { Schema } from "@/types/api";

/** A tournament's flow graph: nodes with their ports, edges and every node's ranked results. */
export type FlowRead = Schema<"tournament.FlowRead">;

export type FlowNodeRead = Schema<"tournament.FlowNodeRead">;

/** Lifecycle status of a node; which values apply depends on its kind. */
export type FlowNodeStatus = Schema<"tournament.FlowNodeStatus">;

/** One phase window (`open`, `check_in`, `start`) of a node. */
export type FlowNodeScheduleEntry = Schema<"tournament.FlowNodeScheduleEntry">;

/** A registration, formation, stage or leaderboard node as `TournamentRead.flow_nodes` carries it. */
export type TournamentFlowNode = Schema<"tournament.TournamentFlowNodeRead">;
