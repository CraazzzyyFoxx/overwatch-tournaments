import TournamentTabBoundary from "../_prefetch";
import TournamentStatsPage from "../_views/TournamentStatsPage";
import { tournamentTeamsQueryOptions } from "@/lib/tournament/teams-query";

type TournamentStatsRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * Only the rosters are prefetched — the default `players` tab lists them; its
 * ranks, the bans and the other tabs' reads load in the browser. The `maps`
 * table costs the whole encounter list with its matches, so the reader who
 * asks for maps waits for one request instead of every reader waiting for it.
 */
export default async function TournamentStatsRoutePage({
  params
}: Readonly<TournamentStatsRoutePageProps>) {
  const { slug } = await params;
  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) =>
        queryClient.prefetchQuery(tournamentTeamsQueryOptions(overview))
      }
    >
      {(overview) => <TournamentStatsPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
