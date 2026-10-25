import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { getTournamentOverviewState } from "./_data";
import { tournamentStreamsQueryOptions, tournamentVodsQueryOptions } from "./_queries/tournamentStreams";
import { mapPoolConfigsQueryOptions } from "@/lib/tournament/map-pool-query";
import { tournamentOverviewQueryOptions } from "@/lib/tournament/overview-query";
import { tournamentRegistrationFormQueryOptions } from "@/lib/tournament/registrations-query";
import {
  areStreamsVisible,
  isTournamentStatusEnded,
  mayHavePastBroadcasts
} from "@/lib/tournament/status";

type TournamentOverviewBoundaryProps = {
  slug: string;
  children: ReactNode;
};

// Seeds the request's React Query cache with the SSR-fetched overview and
// renders the client shell INSIDE that seed, so `useTournamentQuery` resolves
// from it in both renderers. The shell must be a child, not a sibling: the
// server renders a suspended component's siblings before it resolves, so a
// sibling shell built the overview query empty (pending) first, and
// HydrationBoundary only fills an existing query in an effect — which never
// runs on the server. Every cache-missing first visit then streamed the
// skeleton while the browser rendered the page: a hydration mismatch that
// threw the shell away.
//
// The same holds for every OTHER read the shell makes, and those also reach
// the tab below it, so the seed carries all of them (under the shell's own
// gates). An unseeded shell read is created empty on the server before the tab
// resolves — the tab's own prefetch of that key then never applies there —
// and in the browser the shell fetches it before the tab hydrates (React
// hydrates the tab's Suspense boundary in a later pass), so the tab renders
// the data, or an "updating" badge, the server never had. Seeded and fresh,
// the shell makes no first-visit fetch at all. Per-viewer reads (the viewer's
// own registration) stay out: this render is not the viewer's.
export default async function TournamentOverviewBoundary({
  slug,
  children
}: Readonly<TournamentOverviewBoundaryProps>) {
  const overviewState = await getTournamentOverviewState(slug);

  if (overviewState.kind === "not-found") {
    // Intentional streamed soft-404: shell-first TTFB wins for valid refs
    // whose remote lookup misses.
    notFound();
  }

  if (overviewState.kind === "error") {
    // No seed: the shell's own `useTournamentQuery` fails client-side and
    // renders the shared error card itself.
    return children;
  }

  const overview = overviewState.overview;
  const queryClient = new QueryClient();
  queryClient.setQueryData(tournamentOverviewQueryOptions(slug).queryKey, overview);
  // A failed read is just left out (`prefetchQuery` swallows it, `dehydrate`
  // drops it) and the shell retries it client-side.
  await Promise.all([
    // The Maps tab's present-or-absent gate in the nav.
    queryClient.prefetchQuery(mapPoolConfigsQueryOptions(overview.id)),
    // TournamentRegisterButton, rendered until the tournament ends.
    isTournamentStatusEnded(overview.status)
      ? null
      : queryClient.prefetchQuery(tournamentRegistrationFormQueryOptions(overview)),
    // The broadcast dock and the Stream tab, read only while streams show.
    areStreamsVisible(overview.status)
      ? queryClient.prefetchQuery(tournamentStreamsQueryOptions(overview.id))
      : null,
    // The Stream tab's other gate, and the Stream page's past broadcasts.
    mayHavePastBroadcasts(overview.status)
      ? queryClient.prefetchQuery(tournamentVodsQueryOptions(overview.id))
      : null
  ]);

  return <HydrationBoundary state={dehydrate(queryClient)}>{children}</HydrationBoundary>;
}
