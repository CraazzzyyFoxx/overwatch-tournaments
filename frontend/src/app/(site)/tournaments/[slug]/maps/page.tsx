import TournamentTabBoundary from "../_prefetch";
import TournamentMapsPage from "../_views/TournamentMapsPage";
import { catalogListQueryOptions } from "@/lib/catalog/query-options";
import { mapPoolStagesQueryOptions } from "@/lib/tournament/map-pool-query";

type TournamentMapsRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * All three reads of the pool, because the pool is their intersection: the veto
 * configs name map IDs, the catalogue turns those into maps, and the stages
 * name the scopes. Any two of the three would render an empty section. The
 * configs are not prefetched here because the layout's overview boundary
 * already seeds them, under this key, for the nav's Maps tab gate.
 */
export default async function TournamentMapsRoutePage({
  params
}: Readonly<TournamentMapsRoutePageProps>) {
  const { slug } = await params;
  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={async (queryClient, overview) => {
        await Promise.all([
          queryClient.prefetchQuery(mapPoolStagesQueryOptions(overview.id)),
          queryClient.prefetchQuery(catalogListQueryOptions(overview.discipline, "map"))
        ]);
      }}
    >
      {(overview) => <TournamentMapsPage key={overview.id} tournament={overview} />}
    </TournamentTabBoundary>
  );
}
