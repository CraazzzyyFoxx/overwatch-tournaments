import type { Schema } from "@/types/api";
import type { FlowNodeRead } from "@/types/flow.types";

export const LIFECYCLE_KINDS = ["registration", "formation", "stage"] as const;
export const PURE_KINDS = ["filter", "merge", "split", "aggregate", "leaderboard"] as const;

/** The kind as a string literal (the generated `kind` is a TS enum). */
export type FlowNodeKind = `${FlowNodeRead["kind"]}`;

/** A port's unit as a string literal. */
export type FlowUnit = `${Schema<"tournament.FlowUnit">}`;

type StageCreate = Schema<"tournament.StageCreate">;

/** What a new `stage` node carries so the save creates its stage. */
// until P5 Task 1-3 regenerate api types (`FlowNodeUpsert.stage`; `seed_ranking` gains `cross | snake`)
export type FlowStageCreate = Pick<StageCreate, "name"> &
  Partial<Omit<StageCreate, "name" | "stage_type" | "seed_ranking">> & {
    stage_type: `${StageCreate["stage_type"]}`;
    seed_ranking?: string;
  };

export const kindOf = (node: { kind: FlowNodeRead["kind"] }): FlowNodeKind => node.kind;

export const isLifecycle = (kind: FlowNodeKind): boolean => (LIFECYCLE_KINDS as readonly string[]).includes(kind);

export const UNIT_COLOR: Record<FlowUnit, string> = { players: "var(--aqt-blue)", teams: "var(--aqt-amber)" };
