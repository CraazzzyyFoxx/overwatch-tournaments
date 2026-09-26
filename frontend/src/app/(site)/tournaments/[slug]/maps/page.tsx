import TournamentTabBoundary from "../_prefetch";
import TournamentMapsPage from "../_views/TournamentMapsPage";
import { mapsCatalogQueryOptions } from "@/lib/maps/catalog-query";
import {
  mapPoolConfigsQueryOptions,
  mapPoolStagesQueryOptions
} from "@/lib/tournament/map-pool-query";

type TournamentMapsRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * All three reads of the pool, because the pool is their intersection: the veto
 * configs name map IDs, the catalogue turns those into maps, and the stages
 * name the scopes. Prefetching two of the three would render an empty section.
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
          queryClient.prefetchQuery(mapPoolConfigsQueryOptions(overview.id)),
          queryClient.prefetchQuery(mapPoolStagesQueryOptions(overview.id)),
          queryClient.prefetchQuery(mapsCatalogQueryOptions({ withGamemode: true }))
        ]);
      }}
    >
      {(overview) => (
        <TournamentMapsPage key={overview.id} tournamentId={overview.id} slug={slug} />
      )}
    </TournamentTabBoundary>
  );
}
