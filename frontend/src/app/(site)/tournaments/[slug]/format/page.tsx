import TournamentTabBoundary from "../_prefetch";
import TournamentFormatPage from "../_views/TournamentFormatPage";
import { flowQueryOptions } from "../_queries/flow";

type TournamentFormatRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/** Prefetches the flow, so the first paint carries the flow. */
export default async function TournamentFormatRoutePage({
  params
}: Readonly<TournamentFormatRoutePageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) => queryClient.prefetchQuery(flowQueryOptions(overview))}
    >
      {(overview) => <TournamentFormatPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
