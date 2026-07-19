import React from "react";
import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { notFound } from "next/navigation";

import TournamentShellError from "./TournamentShellError";
import { getTournamentOverviewState } from "./_data";
import { tournamentOverviewQueryOptions } from "./_queries/tournamentOverview";

type TournamentOverviewBoundaryProps = {
  tournamentId: number;
  children: React.ReactNode;
};

export default async function TournamentOverviewBoundary({
  tournamentId,
  children
}: TournamentOverviewBoundaryProps) {
  const overviewState = await getTournamentOverviewState(tournamentId);

  if (overviewState.kind === "not-found") {
    // Intentional streamed soft-404: shell-first TTFB wins for valid IDs
    // whose remote lookup misses.
    notFound();
  }

  if (overviewState.kind === "error") {
    return <TournamentShellError />;
  }

  const queryClient = new QueryClient();
  const overviewOptions = tournamentOverviewQueryOptions(tournamentId);
  queryClient.setQueryData(overviewOptions.queryKey, overviewState.overview);

  return <HydrationBoundary state={dehydrate(queryClient)}>{children}</HydrationBoundary>;
}
