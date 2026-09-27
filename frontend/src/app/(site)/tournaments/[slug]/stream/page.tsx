import TournamentTabBoundary from "../_prefetch";
import TournamentStreamPage from "../_views/TournamentStreamPage";

type TournamentPublicStreamPageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * Server component for the tournament id and the shared overview, but with NO
 * stream prefetch.
 *
 * Every field this page renders — live/offline, viewer counts, uptime — is
 * wrong by the time the HTML reaches the reader, and the page is a video player
 * that cannot exist before hydration anyway. Baking a viewer count into a
 * cached-at-the-edge document would be a worse answer than an empty rail that
 * fills in a moment. The shell owns the same `tournamentQueryKeys.streams`
 * entry for its dock, so the read starts once for the whole page regardless.
 */
export default async function TournamentPublicStreamPage({
  params
}: Readonly<TournamentPublicStreamPageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary slug={slug}>
      {(overview) => <TournamentStreamPage key={overview.id} tournamentId={overview.id} />}
    </TournamentTabBoundary>
  );
}
