import TournamentTabBoundary from "../_prefetch";
import TournamentTablePage from "../_views/TournamentTablePage";
import { flowQueryOptions } from "../_queries/flow";

type TournamentTableRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/** Prefetches the flow, so the first paint carries the table. */
export default async function TournamentTableRoutePage({
  params
}: Readonly<TournamentTableRoutePageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) => queryClient.prefetchQuery(flowQueryOptions(overview))}
    >
      {(overview) => <TournamentTablePage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
