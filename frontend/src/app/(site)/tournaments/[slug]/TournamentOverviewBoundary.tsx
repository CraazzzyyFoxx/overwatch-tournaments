import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { notFound } from "next/navigation";

import { getTournamentOverviewState } from "./_data";
import { tournamentOverviewQueryOptions } from "@/lib/tournament/overview-query";

type TournamentOverviewBoundaryProps = {
  slug: string;
};

// Hydration-only: seeds the shared React Query cache with the SSR-fetched
// overview so `useTournamentQuery` resolves instantly wherever it's called
// (TournamentClientLayout and every tab page share the same query key).
// Deliberately renders no children of its own — TournamentClientLayout is a
// sibling in layout.tsx, not a descendant, so a re-suspend here (this segment
// is `force-dynamic`) never unmounts the client shell/nav on tab navigation.
export default async function TournamentOverviewBoundary({
  slug
}: Readonly<TournamentOverviewBoundaryProps>) {
  const overviewState = await getTournamentOverviewState(slug);

  if (overviewState.kind === "not-found") {
    // Intentional streamed soft-404: shell-first TTFB wins for valid refs
    // whose remote lookup misses.
    notFound();
  }

  if (overviewState.kind === "error") {
    // TournamentClientLayout's own `useTournamentQuery` will also fail
    // client-side and render the shared error card itself.
    return null;
  }

  const queryClient = new QueryClient();
  const overviewOptions = tournamentOverviewQueryOptions(slug);
  queryClient.setQueryData(overviewOptions.queryKey, overviewState.overview);

  return <HydrationBoundary state={dehydrate(queryClient)} />;
}
