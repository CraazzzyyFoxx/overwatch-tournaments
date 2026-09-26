import TournamentTabBoundary from "./_prefetch";
import TournamentOverviewPage from "./_views/TournamentOverviewPage";

type TournamentIndexPageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * The bare URL IS the overview screen — no redirect hop to a "first" tab.
 *
 * Its own reads depend on which of the three compositions the status selects,
 * so they are left to the view: the landing screen's first paint is the
 * tournament itself (name, dates, phase, format), and that payload is the one
 * the boundary already hydrates.
 */
export default async function TournamentIndexPage({
  params
}: Readonly<TournamentIndexPageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary slug={slug}>
      {(overview) => (
        <TournamentOverviewPage key={overview.id} tournamentId={overview.id} slug={slug} />
      )}
    </TournamentTabBoundary>
  );
}
