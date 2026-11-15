import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import userService from "@/services/user.service";
import { User } from "@/types/user.types";
import type { StatsScope } from "@/lib/site/stats-scope";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import MatchesTable, { type MatchesFilters } from "@/app/(site)/users/components/matches/MatchesTable";
import type { StageStats } from "@/app/(site)/users/components/matches/MatchesSidebars";
import { USER_ENCOUNTER_ENTITIES } from "@/app/(site)/users/components/shared/encounter-perspective";

const EMPTY_STAGES: StageStats = {
  group: { w: 0, l: 0 },
  playoffs: { w: 0, l: 0 },
  finals: { w: 0, l: 0 }
};

export const UserEncountersPageSkeleton = () => {
  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-16 w-full rounded-xl" />
      <Skeleton className="h-[600px] w-full rounded-xl" />
    </div>
  );
};

export const UserEncountersPage = async ({
  user,
  page,
  filters,
  scope,
  discipline,
  summaryGame,
  sidebarTabs
}: {
  user: User;
  page: number;
  filters?: MatchesFilters;
  scope: StatsScope;
  /** One game, or `null` for every game (the list is cross-game; rows mark their game). */
  discipline: string | null;
  /** The game the (game-bound) matches summary is read in: the page's game, or the per-game tab's under all games. */
  summaryGame: string | null;
  /** The per-game tabs over the summary under "all games". */
  sidebarTabs?: ReactNode;
}) => {
  const perPage = 15;
  const t = await getTranslations();

  let encounters: Awaited<ReturnType<typeof userService.getUserEncounters>>;
  // Most-fought opponents + per-stage record are aggregated server-side over
  // ALL the user's encounters (not just this page); failure is non-fatal.
  let summary: Awaited<ReturnType<typeof userService.getUserMatchesSummary>> | null = null;
  try {
    [encounters, summary] = await Promise.all([
      userService.getUserEncounters(
        user.id,
        discipline,
        page,
        perPage,
        undefined,
        undefined,
        USER_ENCOUNTER_ENTITIES,
        filters,
        scope
      ),
      summaryGame === null
        ? Promise.resolve(null)
        : userService.getUserMatchesSummary(user.id, summaryGame, scope).catch(() => null)
    ]);
  } catch {
    return (
      <PageStateCard state="error" description={t("users.matches.loadError")} className="aqt-player" />
    );
  }

  return (
    <MatchesTable
      encounters={encounters.results}
      total={encounters.total}
      page={page}
      perPage={perPage}
      selfUserId={user.id}
      opponents={summary?.opponents ?? []}
      stages={summary?.stages ?? EMPTY_STAGES}
      allGames={discipline === null}
      sidebarTabs={sidebarTabs}
    />
  );
};
