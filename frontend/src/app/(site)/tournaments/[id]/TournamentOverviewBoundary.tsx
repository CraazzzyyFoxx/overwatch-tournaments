import React from "react";
import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";

import type { Tournament } from "@/types/tournament.types";

import { tournamentOverviewQueryOptions } from "./_queries/tournamentOverview";

type TournamentOverviewBoundaryProps = {
  tournamentId: number;
  overview: Tournament;
  children: React.ReactNode;
};

export default function TournamentOverviewBoundary({
  tournamentId,
  overview,
  children
}: TournamentOverviewBoundaryProps) {
  const queryClient = new QueryClient();
  const overviewOptions = tournamentOverviewQueryOptions(tournamentId);
  queryClient.setQueryData(overviewOptions.queryKey, overview);

  return <HydrationBoundary state={dehydrate(queryClient)}>{children}</HydrationBoundary>;
}
