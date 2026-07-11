import React from "react";
import { User, UserProfile } from "@/types/user.types";
import { AchievementRarity } from "@/types/achievement.types";
import userService from "@/services/user.service";
import { Skeleton } from "@/components/ui/skeleton";
import OverviewLastTournamentCard from "@/app/(site)/users/components/overview/OverviewLastTournamentCard";
import OverviewPlacementSpark from "@/app/(site)/users/components/overview/OverviewPlacementSpark";
import OverviewRoleSplit from "@/app/(site)/users/components/overview/OverviewRoleSplit";
import OverviewMostPlayedHeroes from "@/app/(site)/users/components/overview/OverviewMostPlayedHeroes";
import OverviewRecentEncounters from "@/app/(site)/users/components/overview/OverviewRecentEncounters";
import OverviewCareerList from "@/app/(site)/users/components/overview/OverviewCareerList";
import OverviewTeammatesSynergy from "@/app/(site)/users/components/overview/OverviewTeammatesSynergy";
import OverviewTopHeroesTable from "@/app/(site)/users/components/overview/OverviewTopHeroesTable";
import OverviewAchievementsPreview from "@/app/(site)/users/components/overview/OverviewAchievementsPreview";

export interface OverviewPageProps {
  profile: UserProfile;
  user: User;
  tournamentId?: number;
}

export const UserOverviewPageSkeleton = () => {
  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_380px]">
      <div className="flex min-w-0 flex-col gap-3.5">
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
      <div className="flex min-w-0 flex-col gap-3.5">
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-72 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
        <Skeleton className="h-80 w-full rounded-xl" />
      </div>
    </div>
  );
};

const UserOverviewPage = async ({ profile, tournamentId, user }: OverviewPageProps) => {
  const resolvedTournamentId = tournamentId ?? profile.tournaments[0]?.id;
  const userSlug = user.name.replace("#", "-");

  const [tournament, teammates, tournaments, encounters, heroesRes, mapsRes, achievements] = await Promise.all([
    resolvedTournamentId
      ? userService.getUserTournament(user.id, resolvedTournamentId)
      : Promise.resolve(null),
    userService.getUserBestTeammates(user.id, -1).catch(() => ({ results: [], total: 0 })),
    userService.getUserTournaments(user.id).catch(() => []),
    userService
      .getUserEncounters(user.id, 1, 5, "id", "desc", [
        "tournament",
        "stage",
        "stage_item",
        "home_team",
        "away_team",
        "matches.map"
      ])
      .catch(() => ({ results: [], total: 0 })),
    userService.getUserHeroes(user.id).catch(() => null),
    userService.getUserMaps(user.id, { perPage: -1, minCount: 1 }).catch(() => null),
    userService.getUserAchievements(user.id).catch(() => [] as AchievementRarity[])
  ]);

  const totalSharedMaps = teammates.results.reduce((sum, tm) => sum + (tm.tournaments ?? 0), 0);
  const heroes = heroesRes?.results ?? [];
  const maps = mapsRes?.results ?? [];

  return (
    <div className="aqt-player grid grid-cols-1 gap-3.5 xl:grid-cols-[1fr_380px] xl:items-start">
      <div className="flex min-w-0 flex-col gap-3.5">
        {tournament ? (
          <OverviewLastTournamentCard
            tournament={tournament}
            tournaments={profile.tournaments}
            userId={user.id}
          />
        ) : null}
        <OverviewCareerList profile={profile} tournaments={tournaments} />
        <OverviewPlacementSpark tournaments={tournaments} />
        <OverviewTopHeroesTable heroes={heroes} maps={maps} userSlug={userSlug} />
        <OverviewRecentEncounters
          encounters={encounters.results}
          userName={user.name}
          tournaments={tournaments}
        />
      </div>
      <aside className="flex min-w-0 flex-col gap-3.5 xl:sticky xl:top-[88px]">
        <OverviewRoleSplit profile={profile} heroes={heroes} maps={maps} />
        <OverviewMostPlayedHeroes
          heroes={profile.hero_statistics}
          userSlug={userSlug}
          totalCount={profile.hero_statistics.length}
        />
        <OverviewAchievementsPreview achievements={achievements} userSlug={userSlug} />
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
