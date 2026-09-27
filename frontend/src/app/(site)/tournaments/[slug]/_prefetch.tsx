import type { ReactNode } from "react";
import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { notFound } from "next/navigation";

import { getTournamentOverviewState } from "./_data";
import { tournamentOverviewQueryOptions } from "@/lib/tournament/overview-query";
import type { Tournament } from "@/types/tournament.types";

/**
 * Warms the tab's own reads into the request's query client. Anything it does
 * NOT prefetch simply starts on the client, so this is a first-paint budget,
 * not a completeness requirement.
 */
export type TournamentTabPrefetch = (
  queryClient: QueryClient,
  overview: Tournament
) => Promise<unknown>;

type TournamentTabBoundaryProps = {
  /** The raw `/tournaments/{slug}` URL segment, as the layout resolved it. */
  slug: string;
  prefetch?: TournamentTabPrefetch;
  /**
   * The tab's client view. A render prop because the resolved numeric id is
   * only known once the overview is fetched — which is what this boundary
   * does — and every tab view takes it (and the slug) as plain props.
   */
  children: (overview: Tournament) => ReactNode;
};

/**
 * The server half of a public tournament tab.
 *
 * Every tab used to be a `"use client"` one-liner that read the tournament id
 * from context and let the view fetch everything after hydration: the HTML
 * carried a skeleton, and the tab's own request could not even start until the
 * JS bundle had. This awaits the request-cached overview (the layout is already
 * awaiting the same `cache()`d promise, so it is one upstream read for the
 * whole request), prefetches the tab's first-paint queries under the SAME keys
 * the client hook uses, and hands the view a warm cache — so the tab's content
 * is rendered into the streamed HTML and the client adopts it without a
 * refetch.
 *
 * Every read here goes through the ordinary services: `apiFetch` runs on the
 * server too and injects the tenant/workspace headers.
 */
export default async function TournamentTabBoundary({
  slug,
  prefetch,
  children
}: Readonly<TournamentTabBoundaryProps>) {
  const overviewState = await getTournamentOverviewState(slug);

  if (overviewState.kind === "not-found") {
    // Same streamed soft-404 the layout's overview boundary raises; whichever
    // of the two resolves first wins, and they resolve off one read.
    notFound();
  }

  if (overviewState.kind === "error") {
    // The client shell renders the shared error card for this exact failed
    // read. A second error element below it would be one failure twice.
    return null;
  }

  const overview = overviewState.overview;
  const queryClient = new QueryClient();
  queryClient.setQueryData(tournamentOverviewQueryOptions(slug).queryKey, overview);

  // Prefetch failures are swallowed by `prefetchQuery` on purpose (see each
  // caller): a tab whose own read fails still renders, and the client retries
  // it. `dehydrate` drops the errored entries, so nothing poisons the cache.
  if (prefetch) {
    await prefetch(queryClient, overview);
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>{children(overview)}</HydrationBoundary>
  );
}
