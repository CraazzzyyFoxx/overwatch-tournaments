"use client";

import React, { useMemo } from "react";
import { Sword } from "lucide-react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ui/card";
import GlassGlow from "@/app/(site)/users/compare/components/GlassGlow";
import { getGlowVarsFromColor } from "@/app/(site)/users/compare/utils";
import heroService from "@/services/hero.service";
import tournamentService from "@/services/tournament.service";
import { type SearchableImageOption } from "@/app/(site)/users/compare/components/SearchableImageSelect";

import {
  COL,
  StatKey,
  NUM_COLUMNS,
  getDefaultColumnKeys,
} from "../config/stat-columns";
import HeroLeaderboardFiltersCard from "./HeroLeaderboardFiltersCard";
import HeroLeaderboardTable from "./HeroLeaderboardTable";

const DEFAULT_LG_VARS = {
  "--lg-a": "14 165 233",
  "--lg-b": "16 185 129",
  "--lg-c": "244 63 94",
} as React.CSSProperties;

const HeroLeaderboardContent = () => {
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

  const heroGlowVars = useMemo(
    () => getGlowVarsFromColor(selectedHero?.color ?? null),
    [selectedHero?.color]
  );

  const lgVars = (
    heroGlowVars
      ? { "--lg-a": heroGlowVars["--lg-a"], "--lg-b": heroGlowVars["--lg-b"], "--lg-c": heroGlowVars["--lg-c"] }
      : DEFAULT_LG_VARS
  ) as React.CSSProperties;

  const rows = leaderboardQuery.data?.results ?? [];

  return (
    <div className="liquid-glass space-y-4" style={lgVars}>
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
      />

      {heroId === undefined ? (
        <Card className="relative overflow-hidden">
          <GlassGlow />
          <div className="relative flex flex-col items-center justify-center gap-3 py-20 text-center">
            <Sword className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm leading-relaxed text-muted-foreground">
              Select a hero above to view the leaderboard
            </p>
          </div>
        </Card>
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
