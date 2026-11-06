import type { Schema } from "@/types/api";

/** A tournament's flow graph: nodes with their ports, edges and every node's ranked results. */
export type FlowRead = Schema<"tournament.FlowRead">;

/** One node create/update of a `FlowChanges`; a new `stage` node carries `stage` so the save creates its stage. */
export type FlowNodeUpsert = Schema<"tournament.FlowNodeUpsert">;

/** The stage a new `stage` node creates (`FlowNodeUpsert.stage`). */
export type FlowStageCreate = NonNullable<FlowNodeUpsert["stage"]>;

/** The graph the admin screen reads: the flow plus the validator's issues, the port catalogue and the node config seeds. */
export type AdminFlowRead = Schema<"tournament.AdminFlowRead">;

/** A dry run of a `FlowChanges`: issues and resolved ports per node, under the request's own (negative) ids. */
export type FlowValidationRead = Schema<"tournament.FlowValidationRead">;
export type FlowIssueRead = Schema<"tournament.FlowIssueRead">;
export type FlowPortRead = Schema<"tournament.FlowPortRead">;
export type FlowEdgeRead = Schema<"tournament.FlowEdgeRead">;
export type FlowNodeResultRead = Schema<"tournament.FlowNodeResultRead">;

/** The config each node kind starts with. */
export type FlowConfigDefaults = Schema<"tournament.FlowConfigDefaults">;

/** A node's kind and its port unit as string literals (the generated fields are TS enums). */
export type FlowNodeKind = `${Schema<"tournament.FlowNodeRead">["kind"]}`;
export type FlowUnit = `${NonNullable<FlowPortRead["unit"]>}`;

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
export type FlowNodeScheduleEntry = Omit<Schema<"tournament.FlowNodeScheduleEntry">, "phase"> & {
  phase: `${Schema<"tournament.FlowNodeScheduleEntry">["phase"]}`;
};

/** A registration, formation, stage or leaderboard node as `TournamentRead.flow_nodes` carries it. */
export type TournamentFlowNode = Schema<"tournament.TournamentFlowNodeRead">;
