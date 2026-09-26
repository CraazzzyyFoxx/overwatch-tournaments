import TournamentTabBoundary from "../_prefetch";
import TournamentParticipantsPage from "@/app/(site)/tournaments/[slug]/_views/TournamentParticipantsPage";
import {
  tournamentRegistrationFormQueryOptions,
  tournamentRegistrationsQueryOptions
} from "@/lib/tournament/registrations-query";

type TournamentParticipantsRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * The roster and the form that names its columns — one is unreadable without
 * the other, so both are first paint. The viewer's OWN registration
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
      prefetch={async (queryClient, overview) => {
        await Promise.all([
          queryClient.prefetchQuery(tournamentRegistrationsQueryOptions(overview)),
          queryClient.prefetchQuery(tournamentRegistrationFormQueryOptions(overview))
        ]);
      }}
    >
      {(overview) => <TournamentParticipantsPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
