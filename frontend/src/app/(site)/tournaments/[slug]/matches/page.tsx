import TournamentTabBoundary from "../_prefetch";
import TournamentEncountersPage from "@/app/(site)/tournaments/[slug]/_views/TournamentEncountersPage";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";

type TournamentMatchesPageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * Prefetches the whole match list with its maps — the section IS that list, in
 * either view. Streams are not prefetched: the "who is live" badges are the
 * one part of this page that is worth nothing a second after it is rendered.
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
        <TournamentEncountersPage key={overview.id} tournamentId={overview.id} slug={slug} />
      )}
    </TournamentTabBoundary>
  );
}
