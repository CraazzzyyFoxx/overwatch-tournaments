"use client";

import { useMemo } from "react";
import { Sword } from "lucide-react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import tournamentService from "@/services/tournament.service";
import { type SearchableImageOption } from "@/components/ui/searchable-image-select";

import HeroCompareHero from "./HeroCompareHero";
import HeroLeaderboardControls, { defaultMinGames, parseMinGames } from "./HeroLeaderboardControls";
import HeroRail, { RAIL_MAX_CHARACTERS } from "./HeroRail";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { useCatalogEntities, useCatalogSelection } from "@/hooks/useCatalogEntities";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Skeleton } from "@/components/ui/skeleton";
import { PageStateCard } from "@/components/ui/page-state-card";
import ProfileWidget from "@/components/profile/ProfileWidget";
import { useGameScope } from "@/hooks/useGameScope";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameBoundParams } from "@/components/workspace/scope-pill-store";
import type { GameScopeInit } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";
import { useWorkspaceStore } from "@/stores/workspace.store";

/** The URL params the page itself owns; everything else (a module's board state) is the board's. */
const PAGE_PARAMS = ["discipline", "hero_id", "tournament_id", "min_games"];
/** The URL ids of one game (the page's own params but the game): a pill pick of another game leaves them behind. */
const HERO_GAME_PARAMS = PAGE_PARAMS.filter((param) => param !== "discipline");

/**
 * Character comparison: the host resolves the browsed game, checks the picked character against that game's
 * catalog and owns the tournament scope and the sample floor; the game's module reads and draws everything under
 * the picker (`characterCompare` profile slot). A game without a renderer is told so, and nothing is read for it.
 *
 * The game comes from the site's game switcher only. Under "all games" the page shows the last game played and a
 * chip naming it that opens the switcher; it has no game tabs of its own.
 */
const HeroLeaderboardContent = ({ scope, initial }: Readonly<{ scope: StatsScope; initial: GameScopeInit }>) => {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const heroId = searchParams.get("hero_id") ? Number(searchParams.get("hero_id")) : undefined;
  const tournamentId = searchParams.get("tournament_id")
    ? Number(searchParams.get("tournament_id"))
    : undefined;
  const minGames = parseMinGames(searchParams.get("min_games"), tournamentId);

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
  const setMinGames = (value: number) =>
    updateParams({ min_games: value === defaultMinGames(tournamentId) ? undefined : value });

  // The server's inputs drive the first render, so what it draws is what the browser hydrates.
  const gameScope = useGameScope({ pageClass: "single", initial });
  useGameBoundParams(HERO_GAME_PARAMS);
  const discipline = gameScope.game;
  const heroesQuery = useCatalogEntities(discipline, "character");
  // The id comes from the URL: it must belong to this game's catalog before its statistics are requested (§3.4).
  const heroSelection = useCatalogSelection(discipline, "character", heroId);
  const heroInvalid = heroSelection.status === "invalid";

  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const pickerWorkspaceId = scope === "all" ? "all" : currentWorkspaceId;
  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.selectOptions(pickerWorkspaceId),
    queryFn: () => tournamentService.getAll(null, pickerWorkspaceId),
    staleTime: 5 * 60 * 1000,
  });

  const { axis } = gameScope;
  // The same read the comparison slot waits on (`ProfileWidget`): the rail's class order and role glyphs.
  const metadataQuery = useDisciplineMetadata(axis, discipline);
  const gameName = gameScope.games?.find((entry) => entry.code === discipline)?.name ?? discipline ?? "";
  // Under "all games" the page picked its game itself; the switcher in the header does not name it.
  const gameHint = gameScope.resolution?.tabs && discipline ? gameName : null;

  const heroOptions: SearchableImageOption[] = useMemo(
    () =>
      (heroesQuery.data ?? []).map((hero) => ({
        value: String(hero.id),
        label: hero.name,
        imageSrc: hero.image_path,
      })),
    [heroesQuery.data]
  );
  const railHeroes =
    heroesQuery.data && heroesQuery.data.length > 0 && heroesQuery.data.length <= RAIL_MAX_CHARACTERS
      ? heroesQuery.data
      : null;

  const selectedHero = heroSelection.entity ?? undefined;

  // Only a hero CHECKED valid in this game is handed to the board: an id of another game is never read.
  const heroChecked = heroSelection.status === "valid";
  const compareProps = {
    character: heroChecked ? selectedHero : undefined,
    tournamentId,
    axis,
    minGames,
    onMinGamesChange: setMinGames
  };

  if (gameScope.resolution?.game.kind === "invalid" || gameScope.resolution?.game.kind === "empty") {
    return <GameScopeControl scope={gameScope} variant="single" dropParams={HERO_GAME_PARAMS} headingLevel={1} />;
  }

  return (
    <div className="space-y-[22px]">
      <HeroCompareHero
        aside={
          <HeroLeaderboardControls
            gameHint={gameHint}
            showHeroPicker={!railHeroes && !heroesQuery.isLoading}
            heroId={heroId}
            heroOptions={heroOptions}
            isLoadingHeroes={heroesQuery.isLoading}
            isErrorHeroes={heroesQuery.isError}
            onHeroChange={(v) => updateParams({ hero_id: v ? Number(v) : undefined })}
            tournamentId={tournamentId}
            tournaments={tournamentsQuery.data?.results ?? []}
            isLoadingTournaments={tournamentsQuery.isLoading}
            isErrorTournaments={tournamentsQuery.isError}
            onTournamentChange={(id) => updateParams({ tournament_id: id })}
            minGames={minGames}
            onMinGamesChange={setMinGames}
          />
        }
      />

      {railHeroes ? (
        <HeroRail
          heroes={railHeroes}
          selectedId={heroId}
          ontology={metadataQuery.data}
          onSelect={(id) => updateParams({ hero_id: id })}
        />
      ) : heroesQuery.isLoading ? (
        <Skeleton className="h-[152px] w-full rounded-xl" />
      ) : null}

      {heroSelection.status === "error" ? (
        <PageStateCard
          state="error"
          description={t("users.heroesCompare.invalidHero.checkFailed")}
          onAction={heroSelection.refetch}
          actionLabel={t("common.retry")}
        />
      ) : heroInvalid ? (
        <PageStateCard
          state="error"
          title={t("users.heroesCompare.invalidHero.title")}
          description={t("users.heroesCompare.invalidHero.description", { game: gameName })}
        />
      ) : heroId !== undefined && !heroChecked ? (
        <div className="flex justify-center py-16" role="status" aria-busy="true">
          <Spinner />
        </div>
      ) : heroId === undefined ? (
        <Card className="flex flex-col items-center justify-center gap-3.5 py-[90px] text-center">
          <Sword aria-hidden className="h-10 w-10 text-[color:var(--aqt-fg-faint)] opacity-50" />
          <p className="max-w-sm text-sm leading-relaxed text-[color:var(--aqt-fg-dim)]">
            {t("users.heroesCompare.selectHeroPrompt")}
          </p>
        </Card>
      ) : discipline ? (
        <ProfileWidget
          axis={axis}
          discipline={discipline}
          slot="characterCompare"
          props={compareProps}
          fallback={
            <PageStateCard
              state="empty"
              title={gameName}
              description={t("common.discipline.widgetUnsupported")}
            />
          }
        />
      ) : null}
    </div>
  );
};

export default HeroLeaderboardContent;
