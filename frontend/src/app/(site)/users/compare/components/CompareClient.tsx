"use client";

import { Suspense, useEffect } from "react";
import { Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { CardSurface } from "@/components/profile/atoms";
import ComparePageHero from "@/app/(site)/users/compare/components/ComparePageHero";
import CompareFiltersPanel from "@/app/(site)/users/compare/components/CompareFiltersPanel";
import CompareUnifiedTable, {
  CompareUnifiedTableSkeleton
} from "@/app/(site)/users/compare/components/CompareUnifiedTable";
import { useUserCompareSearchParams } from "@/app/(site)/users/compare/hooks/useUserCompareSearchParams";
import { useUserCompareData } from "@/app/(site)/users/compare/hooks/useUserCompareData";
import { UsersMissingGrid } from "@/app/(site)/users/components/shared/UsersMissingGrid";
import { Spinner } from "@/components/ui/spinner";
import { PageStateCard } from "@/components/ui/page-state-card";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameBoundParams } from "@/components/workspace/scope-pill-store";
import { useGameScope } from "@/hooks/useGameScope";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { isDivisionGridRequired } from "@/lib/api/error";
import type { GameScopeInit } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";

const colorOf = (entity: { attrs: Record<string, unknown> } | undefined) =>
  typeof entity?.attrs.color === "string" ? entity.attrs.color : undefined;
const imageOf = (entity: { image_path: string | null } | undefined) => entity?.image_path ?? undefined;

/** The URL ids and filters of one game: a tab or a pill pick of another game leaves them behind (spec §4.4, R5). */
const COMPARE_GAME_PARAMS = ["role", "div_min", "div_max", "tournament_id", "left_hero_id", "right_hero_id", "map_id"];

const PageContent = ({ scope, initial }: Readonly<{ scope: StatsScope; initial: GameScopeInit }>) => {
  const t = useTranslations();
  const compareParams = useUserCompareSearchParams();
  // A single page (spec §4.3): the scope's game, else `?discipline=` / the last game / the first game with local tabs.
  // The server's inputs drive the first render, so the tabs it draws are the ones the browser hydrates.
  const gameScope = useGameScope({ pageClass: "single", initial });
  useGameBoundParams(COMPARE_GAME_PARAMS);
  const discipline = gameScope.game;
  const roleMetadata = useDisciplineMetadata(gameScope.axis, discipline);

  const {
    compareQuery,
    heroCompareQuery,
    heroes,
    maps,
    tournaments,
    leftHero,
    rightHero,
    selectedSubjectName,
    selectedTargetName,
    baselineSummary,
    rows,
    activeLoading,
    activeRefreshing,
    activeError,
    activeErrorMessage,
    compareDisplayName,
    selectionInvalid,
    selectionsSettled,
    selectionError,
    selectionPending,
    retrySelections,
    heroesQuery,
    mapsQuery,
    tournamentsQuery,
    divisionGrid,
    workspaceId
  } = useUserCompareData({
    isHeroScope: compareParams.isHeroScope,
    subjectUserId: compareParams.subjectUserId,
    effectiveBaseline: compareParams.effectiveBaseline,
    targetUserId: compareParams.targetUserId,
    role: compareParams.role,
    divMin: compareParams.divMin,
    divMax: compareParams.divMax,
    tournamentId: compareParams.tournamentId,
    leftHeroId: compareParams.leftHeroId,
    rightHeroId: compareParams.rightHeroId,
    mapId: compareParams.mapId,
    scope,
    discipline,
    metadata: roleMetadata.data ?? null
  });

  useEffect(() => {
    if (!compareParams.isTargetBaseline) return;
    if (compareParams.divMin === undefined && compareParams.divMax === undefined) return;

    compareParams.updateParams({ div_min: undefined, div_max: undefined });
  }, [
    compareParams.divMax,
    compareParams.divMin,
    compareParams.isTargetBaseline,
    compareParams.updateParams
  ]);

  const activeData = compareParams.isHeroScope
    ? selectionsSettled
      ? heroCompareQuery.data
      : undefined
    : compareQuery.data;
  const sampleSize = activeLoading ? undefined : activeData?.baseline.sample_size;
  const gameName = gameScope.games?.find((entry) => entry.code === discipline)?.name ?? discipline ?? "";
  // Under "all games" the page picked its game itself; the switcher in the header does not name it.
  const gameHint = gameScope.resolution?.tabs && discipline ? gameName : null;
  const retryActiveQuery = () => {
    void (compareParams.isHeroScope ? heroCompareQuery.refetch() : compareQuery.refetch());
  };

  if (gameScope.resolution?.game.kind === "invalid" || gameScope.resolution?.game.kind === "empty") {
    return (
      <div className="aqt-player space-y-3.5">
        <GameScopeControl scope={gameScope} variant="single" dropParams={COMPARE_GAME_PARAMS} headingLevel={1} />
      </div>
    );
  }

  return (
    <div className="aqt-player space-y-3.5">
      <ComparePageHero
        gameHint={gameHint}
        scope={compareParams.scope}
        onScopeChange={(next) => compareParams.updateParams({ scope: next })}
      />
      <CardSurface bodyClassName="space-y-5">
        <CompareFiltersPanel
          ontology={roleMetadata.data}
          subjectUserId={compareParams.subjectUserId}
          targetUserId={compareParams.targetUserId}
          scope={compareParams.scope}
          role={compareParams.role}
          divMin={compareParams.divMin}
          divMax={compareParams.divMax}
          tournamentId={compareParams.tournamentId}
          leftHeroId={compareParams.leftHeroId}
          rightHeroId={compareParams.rightHeroId}
          mapId={compareParams.mapId}
          isTargetBaseline={compareParams.isTargetBaseline}
          selectedSubjectName={selectedSubjectName}
          selectedTargetName={selectedTargetName}
          subjectNameLoading={activeLoading && !selectedSubjectName}
          targetNameLoading={
            Boolean(compareParams.targetUserId) && activeLoading && !selectedTargetName
          }
          divisionGrid={divisionGrid}
          heroes={heroes}
          maps={maps}
          tournaments={tournaments}
          isHeroesLoading={heroesQuery.isLoading}
          isHeroesError={heroesQuery.isError}
          isMapsLoading={mapsQuery.isLoading}
          isMapsError={mapsQuery.isError}
          isTournamentsLoading={tournamentsQuery.isLoading}
          isTournamentsError={tournamentsQuery.isError}
          updateParams={compareParams.updateParams}
        />
      </CardSurface>

      {selectionInvalid ? (
        <PageStateCard
          state="error"
          title={t("users.compare.invalidSelection.title")}
          description={t("users.compare.invalidSelection.description", {
            game: gameName
          })}
        />
      ) : selectionError ? (
        <PageStateCard
          state="error"
          description={t("users.compare.invalidSelection.checkFailed")}
          onAction={retrySelections}
          actionLabel={t("common.retry")}
        />
      ) : isDivisionGridRequired(activeError) && discipline ? (
        <UsersMissingGrid discipline={discipline} gameName={gameName} axis={workspaceId} />
      ) : selectionPending ? (
        <>
          <p className="flex items-center gap-1.5 px-1 text-caption text-[color:var(--aqt-fg-dim)]">
            <span>{baselineSummary}</span>
          </p>
          <CompareUnifiedTableSkeleton isHeroScope={compareParams.isHeroScope} />
        </>
      ) : compareParams.subjectUserId ? (
        <>
          <p aria-live="polite" className="flex items-center gap-1.5 px-1 text-caption text-[color:var(--aqt-fg-dim)]">
            {activeRefreshing ? <Spinner className="size-3 shrink-0" /> : null}
            <span>
              {baselineSummary}
              {sampleSize !== undefined && !compareParams.isTargetBaseline
                ? ` · ${t("users.compare.sampleSize", { count: sampleSize })}`
                : null}
            </span>
          </p>
          <CompareUnifiedTable
            subjectName={
              selectedSubjectName ??
              t("users.compare.userNumber", { id: String(compareParams.subjectUserId) })
            }
            baselineName={compareDisplayName}
            rows={rows}
            loading={activeLoading}
            refreshing={activeRefreshing}
            errorMessage={activeError ? activeErrorMessage : undefined}
            onRetry={retryActiveQuery}
            isHeroScope={compareParams.isHeroScope}
            isTargetBaseline={compareParams.isTargetBaseline}
            subjectHero={{
              name:
                heroCompareQuery.data?.subject_character?.name ??
                leftHero?.name ??
                t("users.compare.allHeroes"),
              imagePath: heroCompareQuery.data?.subject_character?.image_path ?? imageOf(leftHero),
              dominantColor: colorOf(heroCompareQuery.data?.subject_character ?? leftHero),
              playtimeSeconds: heroCompareQuery.data?.left_playtime_seconds ?? 0,
              playtimeLabel: t("users.compare.playtime")
            }}
            baselineHero={{
              name:
                heroCompareQuery.data?.target_character?.name ??
                rightHero?.name ??
                t("users.compare.allHeroes"),
              imagePath: heroCompareQuery.data?.target_character?.image_path ?? imageOf(rightHero),
              dominantColor: colorOf(heroCompareQuery.data?.target_character ?? rightHero),
              playtimeSeconds: heroCompareQuery.data?.right_playtime_seconds ?? 0,
              playtimeLabel: t("users.compare.avgPlaytime")
            }}
          />
        </>
      ) : (
        <CardSurface>
          <div
            aria-live="polite"
            className="flex flex-col items-center justify-center gap-3 py-16 text-center"
          >
            <Users className="h-10 w-10 text-[color:var(--aqt-fg-dim)]" />
            <p className="text-sm text-[color:var(--aqt-fg-muted)]">
              {t("users.compare.selectUserPrompt")}
            </p>
          </div>
        </CardSurface>
      )}
    </div>
  );
};

const CompareClient = ({ scope, initial }: Readonly<{ scope: StatsScope; initial: GameScopeInit }>) => (
  <Suspense fallback={null}>
    <PageContent scope={scope} initial={initial} />
  </Suspense>
);

export default CompareClient;
