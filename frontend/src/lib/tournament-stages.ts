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

export function formatTournamentStages(stages: Tournament["stages"]) {
  return stages
    .map((stage) => stage.name.trim())
    .filter(Boolean)
    .join(", ");
}
