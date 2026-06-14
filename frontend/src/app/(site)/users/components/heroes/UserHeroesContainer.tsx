"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import userService from "@/services/user.service";
import SearchableImageSelect, {
  type SearchableImageOption
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import HeroesView from "@/app/(site)/users/components/heroes/HeroesView";
import { Skeleton } from "@/components/ui/skeleton";

interface UserHeroesContainerProps {
  userId: number;
}

const UserHeroesContainer = ({ userId }: UserHeroesContainerProps) => {
  const [tournamentId, setTournamentId] = useState<number | undefined>(undefined);

  const tournamentsQuery = useQuery({
    queryKey: ["user-tournaments", userId],
    queryFn: () => userService.getUserTournaments(userId),
    staleTime: 5 * 60 * 1000
  });

  const heroesQuery = useQuery({
    queryKey: ["user-heroes", userId, tournamentId],
    queryFn: () => userService.getUserHeroes(userId, undefined, tournamentId),
    staleTime: 5 * 60 * 1000
  });

  // Maps (with per-hero stats) power the "Maps for [Hero]" panel in HeroesView.
  const mapsQuery = useQuery({
    queryKey: ["user-heroes-maps", userId, tournamentId],
    queryFn: () => userService.getUserMaps(userId, { perPage: -1, minCount: 1, tournamentId }),
    staleTime: 5 * 60 * 1000
  });

  const tournamentOptions = useMemo<SearchableImageOption[]>(() => {
    return (tournamentsQuery.data ?? []).map((t) => ({
      value: String(t.id),
      label: t.name
    }));
  }, [tournamentsQuery.data]);

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
        <Skeleton className="h-[600px] w-full rounded-xl" />
      </div>
    );
  }

  const heroes = heroesQuery.data?.results ?? [];

  const filterSlot = (
    <div className="w-60">
      <SearchableImageSelect
        value={tournamentId ? String(tournamentId) : undefined}
        onValueChange={(val) => setTournamentId(val ? Number(val) : undefined)}
        options={tournamentOptions}
        placeholder="All tournaments"
        searchPlaceholder="Search tournament..."
        isLoading={tournamentsQuery.isLoading}
        disabled={tournamentsQuery.isLoading || tournamentsQuery.isError}
      />
    </div>
  );

  return <HeroesView heroes={heroes} filterSlot={filterSlot} maps={mapsQuery.data?.results ?? []} />;
};

export default UserHeroesContainer;
