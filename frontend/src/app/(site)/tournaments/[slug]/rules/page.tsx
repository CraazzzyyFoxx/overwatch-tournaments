import TournamentTabBoundary from "../_prefetch";
import TournamentRulesPage from "../_views/TournamentRulesPage";

type TournamentRulesRoutePageProps = {
  params: Promise<{ slug: string }>;
};

/**
 * No prefetch of its own: `rules` rides in the overview payload this boundary
 * already awaited, so hydrating that one entry renders the whole document —
 * headings, table of contents and all — into the HTML. The only client work
 * left is the scroll-spy that highlights the active section.
 */
export default async function TournamentRulesRoutePage({
  params
}: Readonly<TournamentRulesRoutePageProps>) {
  const { slug } = await params;

  return (
    <TournamentTabBoundary slug={slug}>
      {() => <TournamentRulesPage slug={slug} />}
    </TournamentTabBoundary>
  );
}
