import type { Encounter } from "@/types/encounter.types";

export interface RoundGroup {
  round: number;
  matches: Encounter[];
}

export interface SlotHint {
  home: string | null;
  away: string | null;
}

function sortMatches(matches: Encounter[]) {
  return [...matches].sort((left, right) => {
    const leftKey = left.stage_item_id ?? left.challonge_id ?? left.id;
    const rightKey = right.stage_item_id ?? right.challonge_id ?? right.id;

    return leftKey - rightKey;
  });
}

export function buildRoundGroups(matches: Encounter[]): RoundGroup[] {
  const groups = new Map<number, Encounter[]>();

  for (const match of matches) {
    const existing = groups.get(match.round) ?? [];
    existing.push(match);
    groups.set(match.round, existing);
  }

  return [...groups.entries()]
    .sort((left, right) => Math.abs(left[0]) - Math.abs(right[0]))
    .map(([round, roundMatches]) => ({
      round,
      matches: sortMatches(roundMatches)
    }));
}

export function getRoundSectionMatchCapacity(rounds: RoundGroup[]): number {
  return Math.max(1, ...rounds.map((group) => group.matches.length));
}

export function computeMatchNumbers(
  upperRounds: RoundGroup[],
  lowerRounds: RoundGroup[],
  finalRounds: RoundGroup[]
): Map<number, number> {
  const numbers = new Map<number, number>();
  let counter = 1;
  for (const group of upperRounds) {
    for (const match of group.matches) {
      numbers.set(match.id, counter++);
    }
  }
  for (const group of lowerRounds) {
    for (const match of group.matches) {
      numbers.set(match.id, counter++);
    }
  }
  for (const group of finalRounds) {
    for (const match of group.matches) {
      numbers.set(match.id, counter++);
    }
  }
  return numbers;
}

export function getDoubleEliminationFinalRounds(encounters: Encounter[]): Set<number> {
  const positiveRoundGroups = buildRoundGroups(encounters.filter((match) => match.round > 0));

  if (positiveRoundGroups.length === 0) {
    return new Set();
  }

  let trailingSingleMatchRounds = 0;
  for (let index = positiveRoundGroups.length - 1; index >= 0; index -= 1) {
    if (positiveRoundGroups[index].matches.length !== 1) {
      break;
    }
    trailingSingleMatchRounds += 1;
  }

  const finalRoundCount = Math.max(1, trailingSingleMatchRounds - 1);
  return new Set(positiveRoundGroups.slice(-finalRoundCount).map((group) => group.round));
}

export function getGrandFinalLabel(round: number, groups: RoundGroup[]): string {
  const index = groups.findIndex((group) => group.round === round);

  if (index < 0) {
    return `Round ${round}`;
  }

  if (groups.length === 1) {
    return "Grand Final";
  }

  return index === 0 ? "Grand Final" : "Grand Final Reset";
}

export function computeSlotHints(
  upperRounds: RoundGroup[],
  lowerRounds: RoundGroup[],
  finalRounds: RoundGroup[],
  matchNumbers: Map<number, number>,
  isDE: boolean,
  hasBracketConnections: boolean
): Map<number, SlotHint> {
  const hints = new Map<number, SlotHint>();

  function label(match: Encounter | undefined, prefix: "W" | "L") {
    if (!match) {
      return null;
    }

    const matchNumber = matchNumbers.get(match.id);
    return matchNumber != null ? `${prefix} M${matchNumber}` : null;
  }

  function setHint(target: Encounter, slot: keyof SlotHint, value: string | null) {
    if (!value) {
      return;
    }

    const existing = hints.get(target.id) ?? { home: null, away: null };
    hints.set(target.id, {
      ...existing,
      [slot]: value
    });
  }

  function trackEdges(
    groups: RoundGroup[],
    prefix: "W" | "L",
    mapper: (matchIndex: number, targetCount: number) => number
  ) {
    for (let groupIndex = 0; groupIndex < groups.length - 1; groupIndex += 1) {
      const current = groups[groupIndex].matches;
      const next = groups[groupIndex + 1].matches;
      const feedCount = new Map<number, number>();

      for (let matchIndex = 0; matchIndex < current.length; matchIndex += 1) {
        const targetIndex = mapper(matchIndex, next.length);
        if (targetIndex < 0 || targetIndex >= next.length) {
          continue;
        }

        const target = next[targetIndex];
        const source = current[matchIndex];
        const hintLabel = label(source, prefix);
        if (!hintLabel) {
          continue;
        }

        const count = feedCount.get(targetIndex) ?? 0;
        feedCount.set(targetIndex, count + 1);

        setHint(target, count === 0 ? "home" : "away", hintLabel);
      }
    }
  }

  if (hasBracketConnections) {
    trackEdges(upperRounds, "W", (matchIndex, targetCount) => {
      const targetIndex = Math.floor(matchIndex / 2);
      return targetIndex < targetCount ? targetIndex : -1;
    });
    trackEdges(lowerRounds, "W", (matchIndex, targetCount) => {
      if (targetCount === 0) {
        return -1;
      }
      return Math.min(matchIndex, targetCount - 1);
    });
  }

  if (isDE && upperRounds.length > 0 && lowerRounds.length > 0) {
    const firstLowerRound = lowerRounds[0];
    if (Math.abs(firstLowerRound.round) === 1) {
      firstLowerRound.matches.forEach((target, matchIndex) => {
        setHint(target, "home", label(upperRounds[0].matches[matchIndex * 2], "L"));
        setHint(target, "away", label(upperRounds[0].matches[matchIndex * 2 + 1], "L"));
      });
    }

    for (let upperRoundIndex = 1; upperRoundIndex < upperRounds.length; upperRoundIndex += 1) {
      const targetLowerRound = lowerRounds[upperRoundIndex * 2 - 1];
      if (!targetLowerRound) {
        continue;
      }

      targetLowerRound.matches.forEach((target, matchIndex) => {
        setHint(target, "away", label(upperRounds[upperRoundIndex].matches[matchIndex], "L"));
      });
    }
  }

  if (isDE && finalRounds.length > 0) {
    const grandFinal = finalRounds[0]?.matches[0];
    if (grandFinal) {
      const upperFinal = upperRounds[upperRounds.length - 1]?.matches[0];
      const lowerFinal = lowerRounds[lowerRounds.length - 1]?.matches[0];
      setHint(grandFinal, "home", upperFinal ? label(upperFinal, "W") : null);
      setHint(grandFinal, "away", lowerFinal ? label(lowerFinal, "W") : null);
    }
  }

  return hints;
}
