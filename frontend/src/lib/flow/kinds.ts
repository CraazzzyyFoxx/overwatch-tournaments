import type { FlowNodeKind, FlowNodeRead, FlowUnit } from "@/types/flow.types";

export const LIFECYCLE_KINDS = ["registration", "formation", "stage"] as const;
export const PURE_KINDS = ["filter", "merge", "split", "aggregate", "leaderboard"] as const;

export const kindOf = (node: { kind: FlowNodeRead["kind"] }): FlowNodeKind => node.kind;

export const isLifecycle = (kind: FlowNodeKind): boolean => (LIFECYCLE_KINDS as readonly string[]).includes(kind);

export const UNIT_COLOR: Record<FlowUnit, string> = { players: "var(--aqt-blue)", teams: "var(--aqt-amber)" };
