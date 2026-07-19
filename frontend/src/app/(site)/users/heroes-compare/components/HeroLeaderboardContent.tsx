"use client";

import { useMemo } from "react";
import { Sword } from "lucide-react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import heroService from "@/services/hero.service";
import tournamentService from "@/services/tournament.service";
import { type SearchableImageOption } from "@/app/(site)/users/compare/components/SearchableImageSelect";

import {
  COL,
  StatKey,
  NUM_COLUMNS,
  getDefaultColumnKeys,
} from "../config/stat-columns";
import HeroCompareHero from "./HeroCompareHero";
import HeroLeaderboardFiltersCard from "./HeroLeaderboardFiltersCard";
import HeroLeaderboardTable from "./HeroLeaderboardTable";

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

  const heroesQuery = useQuery({
    queryKey: ["heroes-select-options"],
    queryFn: () => heroService.getAll({ perPage: -1, sort: "name", order: "asc" }),
    staleTime: 5 * 60 * 1000,
  });

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments-select-options"],
    queryFn: () => tournamentService.getAll(),
    staleTime: 5 * 60 * 1000,
  });

  const leaderboardQuery = useQuery({
    queryKey: ["hero-leaderboard", heroId, tournamentId],
    enabled: heroId !== undefined,
    queryFn: () => heroService.getHeroLeaderboard(heroId!, { tournamentId, perPage: -1 }),
  });

  const heroOptions: SearchableImageOption[] = useMemo(
    () =>
      (heroesQuery.data?.results ?? []).map((hero) => ({
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
    () => (heroesQuery.data?.results ?? []).find((h) => h.id === heroId),
    [heroesQuery.data, heroId]
  );

  const selectedTournamentName = useMemo(
    () => tournamentsQuery.data?.results.find((t) => t.id === tournamentId)?.name,
    [tournamentsQuery.data, tournamentId]
  );

  const heroRole = selectedHero?.type ?? selectedHero?.role ?? undefined;
  const defaultKeys = getDefaultColumnKeys(heroRole);
  const columnKeys: StatKey[] = Array.from({ length: NUM_COLUMNS }, (_, i) => {
    const v = searchParams.get(`col${i}`);
    return v && COL[v] ? v : defaultKeys[i] ?? defaultKeys[0];
  });

  const sortDirs = columnKeys.map((key, i): "asc" | "desc" => {
    const v = searchParams.get(`dir${i}`);
    if (v === "asc" || v === "desc") return v;
    return (COL[key]?.ascending ?? false) ? "asc" : "desc";
  });

  const handleColumnSelect = (colIndex: number, key: StatKey) => {
    updateParams({
      [`col${colIndex}`]: key,
      [`dir${colIndex}`]: (COL[key]?.ascending ?? false) ? "asc" : "desc",
    });
  };

  const handleToggleSort = (colIndex: number) => {
    updateParams({ [`dir${colIndex}`]: sortDirs[colIndex] === "asc" ? "desc" : "asc" });
  };

  const handleResetColumns = () => {
    const updates: Record<string, undefined> = {};
    for (let i = 0; i < NUM_COLUMNS; i++) {
      updates[`col${i}`] = undefined;
      updates[`dir${i}`] = undefined;
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
        <div className="flex flex-col items-center justify-center gap-3.5 rounded-[var(--aqt-radius)] border border-[var(--aqt-border)] bg-[var(--aqt-card)] py-[90px] text-center">
          <Sword className="h-10 w-10 text-[var(--aqt-fg-faint)] opacity-50" />
          <p className="max-w-sm text-sm leading-relaxed text-[var(--aqt-fg-dim)]">
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
          sortDirs={sortDirs}
          onColumnSelect={handleColumnSelect}
          onToggleSort={handleToggleSort}
        />
      )}
    </div>
  );
};

export default HeroLeaderboardContent;
