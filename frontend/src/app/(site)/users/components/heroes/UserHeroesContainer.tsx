"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import userService from "@/services/user.service";
import { TournamentCombobox } from "@/app/(site)/users/components/shared/TournamentCombobox";
import HeroesView from "@/app/(site)/users/components/heroes/HeroesView";
import { Skeleton } from "@/components/ui/skeleton";
import { userQueryKeys } from "@/lib/users/query-keys";
import type { StatsScope } from "@/lib/site/stats-scope";

interface UserHeroesContainerProps {
  userId: number;
  scope: StatsScope;
}

const UserHeroesContainer = ({ userId, scope }: UserHeroesContainerProps) => {
  const [tournamentId, setTournamentId] = useState<number | undefined>(undefined);

  const tournamentsQuery = useQuery({
    queryKey: userQueryKeys.tournaments(userId, scope),
    queryFn: () => userService.getUserTournaments(userId, scope === "all" ? "all" : undefined),
    staleTime: 5 * 60 * 1000
  });

  const heroesQuery = useQuery({
    queryKey: userQueryKeys.heroes(userId, tournamentId, scope),
    queryFn: () => userService.getUserHeroes(userId, undefined, tournamentId, scope),
    staleTime: 5 * 60 * 1000
  });

  // Maps (with per-hero stats) power the "Maps for [Hero]" panel in HeroesView.
  const mapsQuery = useQuery({
    queryKey: userQueryKeys.heroMaps(userId, tournamentId, scope),
    queryFn: () =>
      userService.getUserMaps(userId, { perPage: -1, minCount: 1, tournamentId, scope }),
    staleTime: 5 * 60 * 1000
  });

  if (heroesQuery.isLoading) {
    return (
      <div className="aqt-player flex flex-col gap-3.5">
        <div className="flex justify-end">
          <Skeleton className="h-10 w-60 rounded-lg" />
        </div>
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
          <Skeleton className="h-28 w-full rounded-xl" />
          <Skeleton className="h-28 w-full rounded-xl" />
          <Skeleton className="h-28 w-full rounded-xl" />
        </div>
        <Skeleton className="h-150 w-full rounded-xl" />
      </div>
    );
  }

  const heroes = heroesQuery.data?.results ?? [];

  const filterSlot = (
    <div className="w-60">
      <TournamentCombobox
        tournaments={tournamentsQuery.data ?? []}
        value={tournamentId}
        onValueChange={setTournamentId}
        isLoading={tournamentsQuery.isLoading}
        disabled={tournamentsQuery.isLoading || tournamentsQuery.isError}
      />
    </div>
  );

  return <HeroesView heroes={heroes} filterSlot={filterSlot} maps={mapsQuery.data?.results ?? []} />;
};

export default UserHeroesContainer;
