"use client";

import { useQuery } from "@tanstack/react-query";

import { isEncounterCompleted } from "@/lib/encounter/status";
import type { Tournament } from "@/types/tournament.types";

import { createBracketQueryPlan } from "../bracket/bracketData";
import { useFfaStageLobbies } from "./useFfaStageLobbies";

/**
 * How far the tournament has been played, duels and FFA lobbies alike (a lobby
 * is one match of its stage). The bracket's own encounters read and the FFA
 * stage reads, so on the overview — the only place the hero quotes it — this is
 * the cache the page's match blocks already filled. `null` while either read is
 * in flight, and when nothing is drawn yet.
 */
export function useTournamentPlayedCount(
  tournament: Tournament,
  enabled: boolean
): { played: number; total: number } | null {
  const plan = createBracketQueryPlan(tournament, null);
  const encounters = useQuery({
    ...plan.encounters,
    enabled: enabled && plan.initialStageId !== null
  });
  const ffa = useFfaStageLobbies(tournament, enabled);

  if (!enabled || encounters.data === undefined || ffa.isPending) return null;
  const duels = encounters.data.results;
  const total = duels.length + ffa.lobbies.length;
  if (total === 0) return null;
  return {
    played:
      duels.filter(isEncounterCompleted).length + ffa.lobbies.filter(isEncounterCompleted).length,
    total
  };
}
