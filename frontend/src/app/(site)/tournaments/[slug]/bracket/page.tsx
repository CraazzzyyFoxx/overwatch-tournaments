import TournamentTabBoundary from "../_prefetch";
import TournamentBracketPage from "./TournamentBracketPage";
import { createBracketQueryPlan } from "./bracketData";
import type { Stage } from "@/types/tournament.types";

type BracketPageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

/**
 * The bracket's three reads, planned exactly the way the client plans them:
 * the stage list first, then the same plan re-derived from it so `?stage=`
 * resolves against the real structure before the encounters and standings are
 * asked for.
 *
 * `enabled` is an observer flag — `prefetchQuery` does not consult it — so the
 * "no stage to draw yet" case is checked here the way `createBracketQueryPlan`
 * expresses it.
 */
export default async function BracketPage({ params, searchParams }: Readonly<BracketPageProps>) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const stageParam = typeof query.stage === "string" ? query.stage : null;

  return (
    <TournamentTabBoundary
      slug={slug}
      prefetch={async (queryClient, overview) => {
        const summaryPlan = createBracketQueryPlan(overview, stageParam);
        await queryClient.prefetchQuery(summaryPlan.stages);
        const plan = createBracketQueryPlan(
          overview,
          stageParam,
          queryClient.getQueryData<Stage[]>(summaryPlan.stages.queryKey)
        );
        if (plan.initialStageId == null) return;
        await Promise.all([
          queryClient.prefetchQuery(plan.encounters),
          queryClient.prefetchQuery(plan.standings)
        ]);
      }}
    >
      {(overview) => <TournamentBracketPage key={overview.id} slug={slug} />}
    </TournamentTabBoundary>
  );
}
