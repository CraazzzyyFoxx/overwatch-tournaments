import React from "react";
import { User } from "@/types/user.types";
import { Skeleton } from "@/components/ui/skeleton";
import userService from "@/services/user.service";
import TournamentsPlacementTimeline from "@/app/(site)/users/components/redesign/TournamentsPlacementTimeline";
import TournamentsHistory from "@/app/(site)/users/components/redesign/TournamentsHistory";

export const UserTournamentsPageSkeleton = () => {
  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-64 w-full rounded-xl" />
      <Skeleton className="min-h-[400px] w-full rounded-xl" />
    </div>
  );
};

export const UserTournamentsPage = async ({ user }: { user: User }) => {
  const tournaments = await userService.getUserTournaments(user.id);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <TournamentsPlacementTimeline tournaments={tournaments} />
      <TournamentsHistory tournaments={tournaments} selfUserId={user.id} />
    </div>
  );
};
