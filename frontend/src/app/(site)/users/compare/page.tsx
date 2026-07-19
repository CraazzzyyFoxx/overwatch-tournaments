"use client";

import { Suspense, useEffect } from "react";
import { Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import ComparePageHero from "@/app/(site)/users/compare/components/ComparePageHero";
import CompareFiltersPanel from "@/app/(site)/users/compare/components/CompareFiltersPanel";
import CompareUnifiedTable from "@/app/(site)/users/compare/components/CompareUnifiedTable";
import { useUserCompareSearchParams } from "@/app/(site)/users/compare/hooks/useUserCompareSearchParams";
import { useUserCompareData } from "@/app/(site)/users/compare/hooks/useUserCompareData";

const PageContent = () => {
  const t = useTranslations();
  const compareParams = useUserCompareSearchParams();

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
    heroesQuery,
    mapsQuery,
    tournamentsQuery
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
    mapId: compareParams.mapId
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

  const activeData = compareParams.isHeroScope ? heroCompareQuery.data : compareQuery.data;
  const sampleSize = activeData?.baseline.sample_size;
  const retryActiveQuery = () => {
    void (compareParams.isHeroScope ? heroCompareQuery.refetch() : compareQuery.refetch());
  };

  return (
    <div className="aqt-player space-y-3.5">
      <ComparePageHero
        hasSubject={compareParams.subjectUserId !== undefined}
        hasData={activeData !== undefined}
        isLoading={activeLoading}
        isRefreshing={activeRefreshing}
        scope={compareParams.scope}
        baseline={compareParams.effectiveBaseline}
        baselineSummary={baselineSummary}
        sampleSize={sampleSize}
        metricCount={rows.length}
      />

      <CardSurface bodyClassName="space-y-5">
        <CompareFiltersPanel
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

      {compareParams.subjectUserId ? (
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
              heroCompareQuery.data?.subject_hero?.name ??
              leftHero?.name ??
              t("users.compare.allHeroes"),
            imagePath: heroCompareQuery.data?.subject_hero?.image_path ?? leftHero?.image_path,
            dominantColor: heroCompareQuery.data?.subject_hero?.color ?? leftHero?.color,
            playtimeSeconds: heroCompareQuery.data?.left_playtime_seconds ?? 0,
            playtimeLabel: t("users.compare.playtime")
          }}
          baselineHero={{
            name:
              heroCompareQuery.data?.target_hero?.name ??
              rightHero?.name ??
              t("users.compare.allHeroes"),
            imagePath: heroCompareQuery.data?.target_hero?.image_path ?? rightHero?.image_path,
            dominantColor: heroCompareQuery.data?.target_hero?.color ?? rightHero?.color,
            playtimeSeconds: heroCompareQuery.data?.right_playtime_seconds ?? 0,
            playtimeLabel: t("users.compare.avgPlaytime")
          }}
        />
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

const Page = () => {
  return (
    <Suspense fallback={null}>
      <PageContent />
    </Suspense>
  );
};

export default Page;
