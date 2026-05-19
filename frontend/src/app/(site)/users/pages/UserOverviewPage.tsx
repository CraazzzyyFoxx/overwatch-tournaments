import React from "react";
import { User, UserProfile } from "@/types/user.types";
import userService from "@/services/user.service";
import { Skeleton } from "@/components/ui/skeleton";
import OverviewLastTournamentCard from "@/app/(site)/users/components/redesign/OverviewLastTournamentCard";
import OverviewPlacementSpark from "@/app/(site)/users/components/redesign/OverviewPlacementSpark";
import OverviewRoleSplit from "@/app/(site)/users/components/redesign/OverviewRoleSplit";
import OverviewMostPlayedHeroes from "@/app/(site)/users/components/redesign/OverviewMostPlayedHeroes";
import OverviewRecentEncounters from "@/app/(site)/users/components/redesign/OverviewRecentEncounters";
import OverviewCareerList from "@/app/(site)/users/components/redesign/OverviewCareerList";
import OverviewTeammatesSynergy from "@/app/(site)/users/components/redesign/OverviewTeammatesSynergy";

export interface OverviewPageProps {
  profile: UserProfile;
  user: User;
  tournamentId?: number;
}

export const UserOverviewPageSkeleton = () => {
  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_320px]">
      <div className="flex flex-col gap-3.5">
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
          <Skeleton className="h-64 w-full rounded-xl" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
          <Skeleton className="h-80 w-full rounded-xl" />
          <Skeleton className="h-80 w-full rounded-xl" />
        </div>
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
      <div className="flex flex-col gap-3.5">
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
    </div>
  );
};

const UserOverviewPage = async ({ profile, tournamentId, user }: OverviewPageProps) => {
  const resolvedTournamentId = tournamentId ?? profile.tournaments[0]?.id;

  const [tournament, teammates, tournaments, encounters] = await Promise.all([
    resolvedTournamentId
      ? userService.getUserTournament(user.id, resolvedTournamentId)
      : Promise.resolve(null),
    userService.getUserBestTeammates(user.id),
    userService.getUserTournaments(user.id),
    userService.getUserEncounters(user.id, 1, 5)
  ]);

  const totalSharedMaps = teammates.results.reduce((sum, tm) => sum + (tm.tournaments ?? 0), 0);

  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_320px] xl:items-start">
      <div className="flex flex-col gap-3.5">
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
          {tournament ? (
            <OverviewLastTournamentCard tournament={tournament} tournaments={profile.tournaments} />
          ) : null}
          <OverviewPlacementSpark tournaments={tournaments} />
        </div>
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-[1.05fr_1.4fr]">
          <OverviewRoleSplit profile={profile} />
          <OverviewMostPlayedHeroes
            heroes={profile.hero_statistics}
            userSlug={user.name.replace("#", "-")}
            totalCount={profile.hero_statistics.length}
          />
        </div>
        <OverviewRecentEncounters
          encounters={encounters.results}
          userId={user.id}
          userName={user.name}
        />
      </div>
      <aside className="flex flex-col gap-3.5 xl:sticky xl:top-[88px]">
        <OverviewCareerList profile={profile} />
        {teammates.results.length > 0 ? (
          <OverviewTeammatesSynergy
            teammates={teammates.results}
            selfName={user.name}
            totalCount={teammates.total ?? teammates.results.length}
            totalMaps={totalSharedMaps}
          />
        ) : null}
      </aside>
    </div>
  );
};

export default UserOverviewPage;
