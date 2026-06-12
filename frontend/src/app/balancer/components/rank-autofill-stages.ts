import type {
  RankAutofillSourceKey,
  RegistrationRankAutofillStage,
} from "@/types/balancer-admin.types";

/** Lookback window unit for a stage: tournament-based sources vs the time-based OW source. */
export type StageWindowKind = "tournaments" | "days";

/**
 * Window unit per source (structural). Human-readable text — labels, descriptions, unit suffixes
 * and placeholders — lives in i18n (`rankAutofill.source.*`, `rankAutofill.window.*`), looked up
 * by the components, so this module stays presentation-free and unit-testable.
 */
export const STAGE_WINDOW_KIND: Record<RankAutofillSourceKey, StageWindowKind> = {
  ow: "days",
  division_history: "tournaments",
  analytics: "tournaments"
};

/** Default chain: OW → история balancer → аналитика, все включены, без окон. */
export function defaultRankAutofillStages(): RegistrationRankAutofillStage[] {
  return [
    { source: "ow", enabled: true, lookback_days: null },
    { source: "division_history", enabled: true, lookback_tournaments: null },
    { source: "analytics", enabled: true, lookback_tournaments: null }
  ];
}

/** Move a stage from one index to another, returning a new array (or the same ref on no-op). */
export function moveStage(
  stages: RegistrationRankAutofillStage[],
  from: number,
  to: number
): RegistrationRankAutofillStage[] {
  if (from === to || from < 0 || to < 0 || from >= stages.length || to >= stages.length) {
    return stages;
  }
  const next = [...stages];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** Reorder by source ids (convenient for drag-and-drop where ids, not indices, are known). */
export function moveStageBySource(
  stages: RegistrationRankAutofillStage[],
  activeSource: RankAutofillSourceKey,
  overSource: RankAutofillSourceKey
): RegistrationRankAutofillStage[] {
  const from = stages.findIndex((stage) => stage.source === activeSource);
  const to = stages.findIndex((stage) => stage.source === overSource);
  if (from === -1 || to === -1) {
    return stages;
  }
  return moveStage(stages, from, to);
}

/** Toggle the enabled flag of a single stage immutably. */
export function setStageEnabled(
  stages: RegistrationRankAutofillStage[],
  source: RankAutofillSourceKey,
  enabled: boolean
): RegistrationRankAutofillStage[] {
  return stages.map((stage) => (stage.source === source ? { ...stage, enabled } : stage));
}

/** Set the lookback window for a stage, writing to the field that matches its window kind. */
export function setStageLookback(
  stages: RegistrationRankAutofillStage[],
  source: RankAutofillSourceKey,
  value: number | null
): RegistrationRankAutofillStage[] {
  return stages.map((stage) => {
    if (stage.source !== source) {
      return stage;
    }
    return STAGE_WINDOW_KIND[source] === "days"
      ? { ...stage, lookback_days: value }
      : { ...stage, lookback_tournaments: value };
  });
}

/** Current lookback value for a stage, regardless of which field backs it. */
export function stageWindowValue(stage: RegistrationRankAutofillStage): number | null {
  const value =
    STAGE_WINDOW_KIND[stage.source] === "days" ? stage.lookback_days : stage.lookback_tournaments;
  return value ?? null;
}

/** Parse a raw window input: empty / invalid / < 1 → null (no limit); otherwise a positive integer. */
export function parseLookbackInput(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return null;
  }
  return Math.floor(parsed);
}
