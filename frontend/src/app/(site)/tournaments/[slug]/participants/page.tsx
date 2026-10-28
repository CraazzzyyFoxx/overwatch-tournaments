import TournamentTabBoundary from "../_prefetch";
import TournamentParticipantsPage from "@/app/(site)/tournaments/[slug]/_views/TournamentParticipantsPage";
import { tournamentRegistrationsQueryOptions } from "@/lib/tournament/registrations-query";
import { tournamentTeamsQueryOptions } from "@/lib/tournament/teams-query";
import { overviewVariant } from "../_views/tournamentOverview.model";

type TournamentParticipantsRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * The roster is first paint: the registrations until the tournament is over,
 * the teams once it is. The form that names its columns is too, but the
 * layout's overview boundary already seeds it for the shell's Register button
 * — the key the table reads. The viewer's OWN registration
 * (`tournamentQueryKeys.registration`) is deliberately not prefetched: it is
 * per-account state behind the browser's session, and baking one visitor's
 * entry into a shared render is the one mistake this whole change must not
 * make.
 */
export default async function TournamentParticipantsRoutePage({
  params
}: Readonly<TournamentParticipantsRoutePageProps>) {
  const { slug } = await params;
  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={(queryClient, overview) =>
        overviewVariant(overview.status) === "completed"
          ? queryClient.prefetchQuery(tournamentTeamsQueryOptions(overview))
          : queryClient.prefetchQuery(tournamentRegistrationsQueryOptions(overview))
      }
    >
      {(overview) => <TournamentParticipantsPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
