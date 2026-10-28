import TournamentTabBoundary from "../_prefetch";
import TournamentEncountersPage from "@/app/(site)/tournaments/[slug]/_views/TournamentEncountersPage";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";

type TournamentMatchesPageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * Prefetches the whole match list with its maps — the section IS that list, in
 * either view. The streams behind the "who is live" badges are the shell's,
 * seeded by the layout's overview boundary.
 */
export default async function TournamentMatchesPage({
  params
}: Readonly<TournamentMatchesPageProps>) {
  const { slug } = await params;
  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) =>
        queryClient.prefetchQuery(tournamentEncountersQueryOptions(overview))
      }
    >
      {(overview) => (
        <TournamentEncountersPage key={overview.id} tournament={overview} slug={slug} />
      )}
    </TournamentTabBoundary>
  );
}
