"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import userService from "@/services/user.service";
import SearchableImageSelect, {
  type SearchableImageOption
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import HeroesView from "@/app/(site)/users/components/redesign/HeroesView";

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

  const tournamentOptions = useMemo<SearchableImageOption[]>(() => {
    return (tournamentsQuery.data ?? []).map((t) => ({
      value: String(t.id),
      label: t.name
    }));
  }, [tournamentsQuery.data]);

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

  return <HeroesView heroes={heroes} filterSlot={filterSlot} />;
};

export default UserHeroesContainer;
