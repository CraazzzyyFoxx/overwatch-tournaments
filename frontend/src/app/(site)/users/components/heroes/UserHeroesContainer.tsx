"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import userService from "@/services/user.service";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import CharacterStatsTable from "@/components/profile/CharacterStatsTable";
import ProfileWidget from "@/components/profile/ProfileWidget";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { userQueryKeys } from "@/lib/users/query-keys";
import type { StatsScope } from "@/lib/site/stats-scope";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";

interface UserHeroesContainerProps {
  userId: number;
  /** The game's profile tournaments: the tournament filter's options. */
  tournaments: { id: number; name: string }[];
  scope: StatsScope;
  discipline: string;
  /** The viewed workspace axis the game's metadata is read on. */
  axis: WorkspaceAxis;
}

/** The tab's final layout while the characters load: hero picker below xl, hero band with its radar, comparison,
 *  records and maps, the rail. */
const HeroesSkeleton = () => (
  <div aria-busy className="aqt-player flex flex-col gap-3.5">
    <Skeleton className="h-8 w-full rounded-lg sm:w-60 xl:hidden" />
    <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
      <div className="flex min-w-0 flex-col gap-3.5">
        <Skeleton className="h-[34rem] w-full rounded-xl md:h-[26.5rem] lg:h-[16.25rem]" />
        <Skeleton className="h-[21rem] w-full rounded-xl" />
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
          <Skeleton className="h-80 w-full rounded-xl" />
          <Skeleton className="h-80 w-full rounded-xl" />
        </div>
      </div>
      <Skeleton className="hidden h-[40rem] w-full rounded-xl xl:block" />
    </div>
  </div>
);

const UserHeroesContainer = ({ userId, tournaments, scope, discipline, axis }: UserHeroesContainerProps) => {
  const t = useTranslations();
  const [tournamentId, setTournamentId] = useState<number | undefined>(undefined);

  const charactersQuery = useQuery({
    queryKey: userQueryKeys.characters(userId, scope, discipline, tournamentId),
    queryFn: ({ signal }) => userService.getUserCharacters(userId, discipline, { tournamentId, scope, signal }),
    staleTime: 5 * 60 * 1000
  });

  // Maps (with per-character stats) power the "Maps for [character]" panel in HeroesView.
  const mapsQuery = useQuery({
    queryKey: userQueryKeys.characterMaps(userId, scope, discipline, tournamentId),
    queryFn: () => userService.getUserMaps(userId, discipline, { perPage: -1, minCount: 1, tournamentId, scope }),
    staleTime: 5 * 60 * 1000
  });

  if (charactersQuery.isPending) return <HeroesSkeleton />;
  if (charactersQuery.isError) {
    return (
      <PageStateCard
        state="error"
        description={t("common.loadError")}
        onAction={() => void charactersQuery.refetch()}
        className="aqt-player"
      />
    );
  }

  const characters = charactersQuery.data.results;

  const filterSlot = (
    <div className="w-full sm:w-60">
      <TournamentCombobox tournaments={tournaments} value={tournamentId} onValueChange={setTournamentId} />
    </div>
  );

  return (
    <ProfileWidget
      axis={axis}
      discipline={discipline}
      slot="characterStats"
      props={{
        characters,
        maps: mapsQuery.data?.results,
        retryMaps: mapsQuery.isError ? () => void mapsQuery.refetch() : undefined,
        filterSlot
      }}
      fallback={<CharacterStatsTable axis={axis} discipline={discipline} characters={characters} action={filterSlot} />}
    />
  );
};

export default UserHeroesContainer;
