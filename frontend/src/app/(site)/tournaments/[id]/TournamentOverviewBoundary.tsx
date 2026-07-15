import React from "react";
import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { notFound } from "next/navigation";

import { isNotFoundError } from "@/lib/api-error";

import TournamentShellError from "./TournamentShellError";
import { getTournamentOverview } from "./_data";
import { tournamentOverviewQueryOptions } from "./_queries/tournamentOverview";

type TournamentOverviewBoundaryProps = {
  tournamentId: number;
  children: React.ReactNode;
};

export default async function TournamentOverviewBoundary({
  tournamentId,
  children,
}: TournamentOverviewBoundaryProps) {
  let overview;

  try {
    overview = await getTournamentOverview(tournamentId);
  } catch (error) {
    if (isNotFoundError(error)) {
      notFound();
    }

    return <TournamentShellError />;
  }

  const queryClient = new QueryClient();
  const overviewOptions = tournamentOverviewQueryOptions(tournamentId);
  queryClient.setQueryData(overviewOptions.queryKey, overview);

  return <HydrationBoundary state={dehydrate(queryClient)}>{children}</HydrationBoundary>;
}
