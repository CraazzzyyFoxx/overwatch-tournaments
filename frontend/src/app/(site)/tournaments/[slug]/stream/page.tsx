import TournamentTabBoundary from "../_prefetch";
import TournamentStreamPage from "../_views/TournamentStreamPage";

type TournamentPublicStreamPageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * Server component for the tournament id and the shared overview; no prefetch
 * of its own. The reads this page renders are the shell's: the layout's
 * overview boundary seeds `tournamentQueryKeys.streams` (the broadcast dock and
 * the nav's Stream tab) and `tournamentQueryKeys.vods` (the tab's other gate),
 * and this view reads those same entries.
 */
export default async function TournamentPublicStreamPage({
  params
}: Readonly<TournamentPublicStreamPageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary slug={slug}>
      {(overview) => (
        <TournamentStreamPage key={overview.id} tournamentId={overview.id} slug={slug} />
      )}
    </TournamentTabBoundary>
  );
}
