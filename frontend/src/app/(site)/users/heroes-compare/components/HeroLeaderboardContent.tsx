"use client";

import { useMemo } from "react";
import { Sword } from "lucide-react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import heroService from "@/services/hero.service";
import tournamentService from "@/services/tournament.service";
import { type SearchableImageOption } from "@/components/ui/searchable-image-select";

import {
  COL,
  StatKey,
  NUM_COLUMNS,
  getDefaultColumnKeys,
} from "../config/stat-columns";
import HeroCompareHero from "./HeroCompareHero";
import HeroLeaderboardFiltersCard from "./HeroLeaderboardFiltersCard";
import HeroLeaderboardTable from "./HeroLeaderboardTable";
import { heroQueryKeys } from "@/lib/heroes/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { useHeroesCatalog } from "@/hooks/useHeroesCatalog";

const HeroLeaderboardContent = () => {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const heroId = searchParams.get("hero_id") ? Number(searchParams.get("hero_id")) : undefined;
  const tournamentId = searchParams.get("tournament_id")
    ? Number(searchParams.get("tournament_id"))
    : undefined;

  const updateParams = (updates: Record<string, string | number | undefined>) => {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === undefined || value === null) {
        params.delete(key);
      } else {
        params.set(key, String(value));
      }
    }
    router.replace(`${pathname}?${params.toString()}`);
  };

  const heroesQuery = useHeroesCatalog();

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.selectOptions(),
    queryFn: () => tournamentService.getAll(),
    staleTime: 5 * 60 * 1000,
  });

  const leaderboardQuery = useQuery({
    queryKey: heroQueryKeys.leaderboard(heroId, tournamentId),
    enabled: heroId !== undefined,
    queryFn: () => heroService.getHeroLeaderboard(heroId!, { tournamentId, perPage: -1 }),
  });

  const heroOptions: SearchableImageOption[] = useMemo(
    () =>
      (heroesQuery.data ?? []).map((hero) => ({
        value: String(hero.id),
        label: hero.name,
        imageSrc: hero.image_path,
      })),
    [heroesQuery.data]
  );

  const tournamentOptions: SearchableImageOption[] = useMemo(
    () =>
      (tournamentsQuery.data?.results ?? []).map((t) => ({
        value: String(t.id),
        label: t.name,
      })),
    [tournamentsQuery.data]
  );

  const selectedHero = useMemo(
    () => (heroesQuery.data ?? []).find((h) => h.id === heroId),
    [heroesQuery.data, heroId]
  );

  const selectedTournamentName = useMemo(
    () => tournamentsQuery.data?.results.find((t) => t.id === tournamentId)?.name,
    [tournamentsQuery.data, tournamentId]
  );

  const heroRole = selectedHero?.type ?? selectedHero?.role ?? undefined;
  const defaultKeys = useMemo(() => getDefaultColumnKeys(heroRole), [heroRole]);

  // Memoized so the table's per-column bar scales and its memoized rows stay
  // stable across renders that only change hover state.
  const columnKeys = useMemo<StatKey[]>(
    () =>
      Array.from({ length: NUM_COLUMNS }, (_, i) => {
        const v = searchParams.get(`col${i}`);
        return v && COL[v] ? v : defaultKeys[i] ?? defaultKeys[0];
      }),
    [searchParams, defaultKeys]
  );

  // A single active column drives the shared row order of the whole table.
  const rawSortIndex = Number(searchParams.get("sort"));
  const sortIndex =
    Number.isInteger(rawSortIndex) && rawSortIndex >= 0 && rawSortIndex < NUM_COLUMNS
      ? rawSortIndex
      : 0;

  const dirParam = searchParams.get("dir");
  const sortDir: "asc" | "desc" =
    dirParam === "asc" || dirParam === "desc"
      ? dirParam
      : (COL[columnKeys[sortIndex]]?.ascending ?? false)
        ? "asc"
        : "desc";

  const handleColumnSelect = (colIndex: number, key: StatKey) => {
    const updates: Record<string, string | number | undefined> = { [`col${colIndex}`]: key };
    // Swapping the stat the sorted column shows resets to that stat's natural direction.
    if (colIndex === sortIndex) {
      updates.dir = (COL[key]?.ascending ?? false) ? "asc" : "desc";
    }
    updateParams(updates);
  };

  const handleSortChange = (colIndex: number) => {
    if (colIndex === sortIndex) {
      updateParams({ dir: sortDir === "asc" ? "desc" : "asc" });
      return;
    }
    updateParams({
      sort: colIndex,
      dir: (COL[columnKeys[colIndex]]?.ascending ?? false) ? "asc" : "desc",
    });
  };

  const handleResetColumns = () => {
    const updates: Record<string, undefined> = { sort: undefined, dir: undefined };
    for (let i = 0; i < NUM_COLUMNS; i++) {
      updates[`col${i}`] = undefined;
    }
    updateParams(updates);
  };

  const rows = leaderboardQuery.data?.results ?? [];

  return (
    <div className="space-y-[22px]">
      <HeroCompareHero selectedHero={selectedHero} rows={rows} />

      <HeroLeaderboardFiltersCard
        heroId={heroId}
        tournamentId={tournamentId}
        heroOptions={heroOptions}
        tournamentOptions={tournamentOptions}
        isLoadingHeroes={heroesQuery.isLoading}
        isErrorHeroes={heroesQuery.isError}
        isLoadingTournaments={tournamentsQuery.isLoading}
        isErrorTournaments={tournamentsQuery.isError}
        onHeroChange={(v) => updateParams({ hero_id: v ? Number(v) : undefined })}
        onTournamentChange={(v) => updateParams({ tournament_id: v ? Number(v) : undefined })}
        onResetColumns={handleResetColumns}
        resetDisabled={heroId === undefined}
      />

      {heroId === undefined ? (
        <div className="flex flex-col items-center justify-center gap-3.5 rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-[90px] text-center">
          <Sword aria-hidden className="h-10 w-10 text-[color:var(--aqt-fg-faint)] opacity-50" />
          <p className="max-w-sm text-sm leading-relaxed text-[color:var(--aqt-fg-dim)]">
            {t("users.heroesCompare.selectHeroPrompt")}
          </p>
        </div>
      ) : (
        <HeroLeaderboardTable
          selectedHero={selectedHero}
          selectedTournamentName={selectedTournamentName}
          tournamentId={tournamentId}
          rows={rows}
          isLoading={leaderboardQuery.isLoading}
          columnKeys={columnKeys}
          sortIndex={sortIndex}
          sortDir={sortDir}
          onColumnSelect={handleColumnSelect}
          onSortChange={handleSortChange}
        />
      )}
    </div>
  );
};

export default HeroLeaderboardContent;
