import React from "react";
import userService from "@/services/user.service";
import { User } from "@/types/user.types";
import { Skeleton } from "@/components/ui/skeleton";
import MatchesTable, { type MatchesFilters } from "@/app/(site)/users/components/matches/MatchesTable";

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

  let encounters: Awaited<ReturnType<typeof userService.getUserEncounters>>;
  try {
    encounters = await userService.getUserEncounters(user.id, page, perPage, undefined, undefined, undefined, filters);
  } catch {
    return (
      <div className="aqt-player rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-6 py-10 text-center text-[13px] text-[color:var(--aqt-fg-muted)]">
        Could not load matches. Please try again later.
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
    />
  );
};
