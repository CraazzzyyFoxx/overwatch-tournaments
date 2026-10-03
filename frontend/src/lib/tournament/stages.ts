import { BRACKET_STAGE_TYPES } from "@/lib/bracket/projection";
import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import type { StageSummary, Tournament, TournamentStatus } from "@/types/tournament.types";

/**
 * The tournament's current stage: the one answer to "which stage do we open",
 * shared by the overview cards, the bracket's landing stage (no `?stage=`), the
 * section nav's bracket link and the list's progress label.
 *
 * The one being played now; after the tournament ends, the playoff that
 * decided it. Unpublished stages (drafts, an organizer's preview) are skipped
 * while anything is published, so a playoff nobody started never outranks an
 * unfinished or just-finished group stage; with nothing published, the first
 * unfinished stage is meant.
 *
 * A phase running parallel divisions has no single answer, so `order` then id
 * decides.
 */
export function pickCurrentStage<T extends StageSummary>(
  stages: readonly T[],
  status: TournamentStatus
): T | null {
  const ordered = [...stages].sort((left, right) => left.order - right.order || left.id - right.id);
  const visible = ordered.filter((stage) => stage.is_published || stage.is_completed);
  const pool = visible.length > 0 ? visible : ordered;

  if (reachedAtLeast(status, "completed")) {
    return (
      pool.filter((stage) => BRACKET_STAGE_TYPES.includes(stage.stage_type)).at(-1) ??
      pool.at(-1) ??
      null
    );
  }
  return (
    pool.find((stage) => stage.is_active) ??
    pool.find((stage) => !stage.is_completed) ??
    pool.at(-1) ??
    null
  );
}

/** Stages with the same `order` are one phase (parallel brackets). */
export function groupTournamentStageFlow<T extends { id: number; order: number }>(
  stages: readonly T[]
): T[][] {
  const ordered = [...stages].sort((left, right) => left.order - right.order || left.id - right.id);
  const waves: T[][] = [];
  for (const stage of ordered) {
    const wave = waves.at(-1);
    if (wave !== undefined && wave.at(0)?.order === stage.order) wave.push(stage);
    else waves.push([stage]);
  }
  return waves;
}

export function nextStageOrder(stages: readonly { order: number }[]): number {
  return Math.max(-1, ...stages.map((stage) => stage.order)) + 1;
}

/**
 * The phase number each stage takes after a drag: the tournament's existing
 * numbers, ascending, handed back out top to bottom.
 *
 * Dragging moves a stage between phases; it never renumbers them. Gaps (0, 2,
 * 5) and shared numbers (a Low and a High division on 1) are the organizer's,
 * and densifying them into 0..n-1 would silently rewire "which stage feeds
 * which".
 */
export function phaseOrderForArrangement<T extends { id: number; order: number }>(
  arrangement: readonly T[]
): Map<number, number> {
  const numbers = arrangement.map((stage) => stage.order).sort((left, right) => left - right);
  return new Map(arrangement.map((stage, index) => [stage.id, numbers[index]]));
}

export function formatTournamentStages(stages: Tournament["stages"]) {
  return stages
    .map((stage) => stage.name.trim())
    .filter(Boolean)
    .join(", ");
}
