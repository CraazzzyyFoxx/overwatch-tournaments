import React from "react";
import { User } from "@/types/user.types";
import { Skeleton } from "@/components/ui/skeleton";
import userService from "@/services/user.service";
import TournamentsHistory from "@/app/(site)/users/components/tournaments/TournamentsHistory";

export const UserTournamentsPageSkeleton = () => {
  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-24 w-full rounded-xl" />
      <Skeleton className="h-56 w-full rounded-xl" />
      <Skeleton className="min-h-[400px] w-full rounded-xl" />
    </div>
  );
};

export const UserTournamentsPage = async ({ user }: { user: User }) => {
  // Both reads are workspace-scoped and cached (Next Data Cache); fetched in
  // parallel. The profile powers the KPI strip (Played / Titles / Avg placement);
  // the tournaments list drives the master-detail Event dossier explorer.
  const [tournaments, profile] = await Promise.all([
    userService.getUserTournaments(user.id),
    userService.getUserProfile(user.id).catch(() => null)
  ]);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <TournamentsHistory tournaments={tournaments} selfUserId={user.id} profile={profile} />
    </div>
  );
};
