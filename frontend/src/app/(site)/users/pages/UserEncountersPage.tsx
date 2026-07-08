import React from "react";
import { getTranslations } from "next-intl/server";
import userService from "@/services/user.service";
import { User } from "@/types/user.types";
import { Skeleton } from "@/components/ui/skeleton";
import MatchesTable, { type MatchesFilters } from "@/app/(site)/users/components/matches/MatchesTable";
import type { StageStats } from "@/app/(site)/users/components/matches/MatchesSidebars";

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
  filters
}: {
  user: User;
  page: number;
  filters?: MatchesFilters;
}) => {
  const perPage = 15;
  const t = await getTranslations();

  let encounters: Awaited<ReturnType<typeof userService.getUserEncounters>>;
  // Most-fought opponents + per-stage record are aggregated server-side over
  // ALL the user's encounters (not just this page); failure is non-fatal.
  let summary: Awaited<ReturnType<typeof userService.getUserMatchesSummary>> | null = null;
  try {
    [encounters, summary] = await Promise.all([
      userService.getUserEncounters(user.id, page, perPage, undefined, undefined, undefined, filters),
      userService.getUserMatchesSummary(user.id).catch(() => null)
    ]);
  } catch {
    return (
      <div className="aqt-player rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-6 py-10 text-center text-[13px] text-[color:var(--aqt-fg-muted)]">
        {t("users.matches.loadError")}
      </div>
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
    />
  );
};
