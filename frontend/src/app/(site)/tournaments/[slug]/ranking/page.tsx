import TournamentTabBoundary from "../_prefetch";
import TournamentRankingPage from "../_views/TournamentRankingPage";
import { playerStandingsQueryOptions } from "../_queries/individualSwiss";

type TournamentRankingRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/** Prefetches the personal table, so the first paint carries it. */
export default async function TournamentRankingRoutePage({
  params
}: Readonly<TournamentRankingRoutePageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) =>
        queryClient.prefetchQuery(playerStandingsQueryOptions(overview))
      }
    >
      {(overview) => <TournamentRankingPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
