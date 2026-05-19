import React from "react";
import userService from "@/services/user.service";
import { User } from "@/types/user.types";
import { Skeleton } from "@/components/ui/skeleton";
import MatchesTable from "@/app/(site)/users/components/redesign/MatchesTable";

export const UserEncountersPageSkeleton = () => {
  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-16 w-full rounded-xl" />
      <Skeleton className="h-[600px] w-full rounded-xl" />
    </div>
  );
};

export const UserEncountersPage = async ({ user, page }: { user: User; page: number }) => {
  const perPage = 15;
  const encounters = await userService.getUserEncounters(user.id, page, perPage);

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
