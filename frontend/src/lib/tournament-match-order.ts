import type { Encounter } from "@/types/encounter.types";

export function getDoubleEliminationRoundOrder(roundNum: number): number {
  if (roundNum === 1) return 1.0;
  if (roundNum === -1) return 2.0;
  if (roundNum > 1) return 3.0 * roundNum - 3.0;
  if (roundNum < -1) {
    const val = Math.abs(roundNum);
    if (val % 2 === 0) {
      const k = val / 2;
      return 3.0 * k + 1.0;
    } else {
      const k = (val - 1) / 2;
      return 3.0 * k + 2.0;
    }
  }
  return 0.0;
}

export function sortStandingsMatches(matches: Encounter[]): Encounter[] {
  if (matches.length === 0) {
    return [];
  }

  const hasNegativeRounds = matches.some((m) => m.round < 0);

  return [...matches].sort((left, right) => {
    const leftScore = hasNegativeRounds ? getDoubleEliminationRoundOrder(left.round) : left.round;
    const rightScore = hasNegativeRounds ? getDoubleEliminationRoundOrder(right.round) : right.round;

    if (leftScore !== rightScore) {
      return leftScore - rightScore;
    }

    return left.id - right.id;
  });
}
