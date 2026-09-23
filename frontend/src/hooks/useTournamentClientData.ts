"use client";

import { useQuery } from "@tanstack/react-query";

import { tournamentOverviewQueryOptions } from "@/lib/tournament/overview-query";

export function useTournamentQuery(slug: string) {
  return useQuery({
    ...tournamentOverviewQueryOptions(slug),
    enabled: slug.length > 0,
  });
}
