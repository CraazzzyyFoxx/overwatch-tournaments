import type { Tournament } from "@/types/tournament.types";

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
