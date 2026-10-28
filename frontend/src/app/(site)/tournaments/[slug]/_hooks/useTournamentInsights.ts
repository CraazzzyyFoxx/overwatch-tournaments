"use client";

import { useQuery } from "@tanstack/react-query";

import {
  tournamentDraftQueryOptions,
  tournamentPickBanOutcomesQueryOptions,
  tournamentPlayerStatsQueryOptions,
  type TournamentInsights
} from "@/lib/tournament/insights-query";
import type { Tournament } from "@/types/tournament.types";

const NO_PLAYERS: TournamentInsights["players"] = {};
const NO_BANS: TournamentInsights["heroBans"] = [];
const NO_MAP_BANS: TournamentInsights["mapBans"] = [];

/**
 * The per-player ranks, the bans and the draft the overview, statistics and participants views read beyond their
 * own tabs' queries. Fetched in the browser only; until (or unless) a read answers, its part is empty, so a view
 * shows its empty state. `isPending`: the stats or the bans are still on their way.
 */
export function useTournamentInsights(
  tournament: Pick<Tournament, "id" | "status">
): TournamentInsights & { isPending: boolean } {
  const stats = useQuery(tournamentPlayerStatsQueryOptions(tournament));
  const bans = useQuery(tournamentPickBanOutcomesQueryOptions(tournament));
  const draft = useQuery(tournamentDraftQueryOptions(tournament));
  return {
    players: stats.data?.players ?? NO_PLAYERS,
    playersTotal: stats.data?.playersTotal ?? 0,
    heroBans: bans.data?.heroBans ?? NO_BANS,
    mapBans: bans.data?.mapBans ?? NO_MAP_BANS,
    draft: draft.data ?? null,
    isPending: stats.isPending || bans.isPending
  };
}
