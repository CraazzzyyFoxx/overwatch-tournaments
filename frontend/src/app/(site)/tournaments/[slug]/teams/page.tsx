import TournamentTabBoundary from "../_prefetch";
import TournamentTeamsPage from "@/app/(site)/tournaments/[slug]/_views/TournamentTeamsPage";
import { tournamentTeamsQueryOptions } from "@/lib/tournament/teams-query";

type TournamentTeamsRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * Prefetches the roster itself. The W–L column (encounters) and the declared
 * heroes (registrations + hero catalogue) are secondary: the table renders
 * without them, so they stay client reads rather than three more round trips
 * in front of the first byte.
 */
export default async function TournamentTeamsRoutePage({
  params
}: Readonly<TournamentTeamsRoutePageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) =>
        queryClient.prefetchQuery(tournamentTeamsQueryOptions(overview))
      }
    >
      {(overview) => <TournamentTeamsPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
