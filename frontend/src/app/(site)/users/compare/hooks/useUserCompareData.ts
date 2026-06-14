"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import heroService from "@/services/hero.service";
import mapService from "@/services/map.service";
import tournamentService from "@/services/tournament.service";
import userService from "@/services/user.service";
import { UserRoleType, UserCompareBaselineMode } from "@/types/user.types";
import { CompareRow } from "@/app/(site)/users/compare/types";
import { getHumanizedStats } from "@/utils/stats";
import { HERO_COMPARE_STATS } from "@/app/(site)/users/compare/constants";
import { getMapIconSrc, normalizeNumber } from "@/app/(site)/users/compare/utils";

interface UseUserCompareDataParams {
  isHeroScope: boolean;
  subjectUserId?: number;
  effectiveBaseline: UserCompareBaselineMode;
  targetUserId?: number;
  role?: UserRoleType;
  divMin?: number;
  divMax?: number;
  tournamentId?: number;
  leftHeroId?: number;
  rightHeroId?: number;
  mapId?: number;
}

export const useUserCompareData = ({
  isHeroScope,
  subjectUserId,
  effectiveBaseline,
  targetUserId,
  role,
  divMin,
  divMax,
  tournamentId,
  leftHeroId,
  rightHeroId,
  mapId
}: UseUserCompareDataParams) => {
  const compareQuery = useQuery({
    queryKey: ["user-compare", subjectUserId, effectiveBaseline, targetUserId, role, divMin, divMax, tournamentId],
    enabled: !isHeroScope && subjectUserId !== undefined,
    queryFn: () =>
      userService.getUserCompare(subjectUserId!, {
        baseline: effectiveBaseline,
        targetUserId,
        role,
        divMin,
        divMax,
        tournamentId
      })
  });

  const heroesQuery = useQuery({
    queryKey: ["heroes-select-options"],
    queryFn: () =>
      heroService.getAll({
        perPage: -1,
        sort: "name",
        order: "asc"
      }),
    staleTime: 5 * 60 * 1000
  });

  const mapsQuery = useQuery({
    queryKey: ["maps-select-options"],
    queryFn: () =>
      mapService.getAll({
        perPage: -1,
        sort: "name",
        order: "asc"
      }),
    staleTime: 5 * 60 * 1000
  });

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments-select-options"],
    queryFn: () => tournamentService.getAll(),
    staleTime: 5 * 60 * 1000
  });

  const heroCompareQuery = useQuery({
    queryKey: [
      "user-hero-compare",
      subjectUserId,
      effectiveBaseline,
      targetUserId,
      role,
      divMin,
      divMax,
      tournamentId,
      leftHeroId,
      rightHeroId,
      mapId
    ],
    enabled: isHeroScope && subjectUserId !== undefined,
    queryFn: () =>
      userService.getUserHeroCompare(subjectUserId!, {
        baseline: effectiveBaseline,
        targetUserId,
        leftHeroId,
        rightHeroId,
        mapId,
        role,
        divMin,
        divMax,
        tournamentId,
        stats: HERO_COMPARE_STATS
      })
  });

  const heroes = heroesQuery.data?.results ?? [];
  const maps = mapsQuery.data?.results ?? [];
  const tournaments = tournamentsQuery.data?.results ?? [];

  const heroMapById = useMemo(() => new Map(heroes.map((hero) => [hero.id, hero])), [heroes]);
  const mapById = useMemo(() => new Map(maps.map((map) => [map.id, map])), [maps]);

  const leftHero = leftHeroId ? heroMapById.get(leftHeroId) : undefined;
  const rightHero = rightHeroId ? heroMapById.get(rightHeroId) : undefined;
  const selectedMap = mapId ? mapById.get(mapId) : undefined;

  const selectedSubjectName = compareQuery.data?.subject.name ?? heroCompareQuery.data?.subject.name;
  const selectedTargetName = compareQuery.data?.baseline.target_user?.name ?? heroCompareQuery.data?.target?.name;

  const baselineSummary = useMemo(() => {
    if (effectiveBaseline === "target_user") {
      return selectedTargetName ? `Comparing against ${selectedTargetName}` : "Comparing against selected user";
    }

    if (effectiveBaseline === "cohort") {
      const roleText = role ?? "All roles";
      const rangeText = `${divMin ?? "Any"} - ${divMax ?? "Any"}`;
      return `Comparing against cohort averages (${roleText}, division ${rangeText})`;
    }

    return "Comparing against global all-players averages";
  }, [effectiveBaseline, selectedTargetName, role, divMin, divMax]);

  const rows = useMemo<CompareRow[]>(() => {
    if (isHeroScope) {
      if (!heroCompareQuery.data) return [];
      return heroCompareQuery.data.metrics.map((metric) => ({
        key: metric.stat,
        label: getHumanizedStats(metric.stat),
        subjectValue: normalizeNumber(metric.left_value),
        baselineValue: normalizeNumber(metric.right_value),
        delta: normalizeNumber(metric.delta),
        deltaPercent: normalizeNumber(metric.delta_percent),
        percentile: null,
        betterWorse: metric.better_worse,
        higherIsBetter: metric.higher_is_better
      }));
    }

    if (!compareQuery.data) return [];
    return compareQuery.data.metrics.map((metric) => ({
      key: metric.key,
      label: metric.label.replace("/10", "").trim(),
      subjectValue: normalizeNumber(metric.subject_value),
      baselineValue: normalizeNumber(metric.baseline_value),
      delta: normalizeNumber(metric.delta),
      deltaPercent: normalizeNumber(metric.delta_percent),
      percentile: normalizeNumber(metric.subject_percentile),
      betterWorse: metric.better_worse,
      higherIsBetter: metric.higher_is_better
    }));
  }, [isHeroScope, compareQuery.data, heroCompareQuery.data]);

  const activeLoading = isHeroScope ? heroCompareQuery.isLoading : compareQuery.isLoading;
  const activeError = isHeroScope ? heroCompareQuery.error : compareQuery.error;
  const activeErrorMessage =
    activeError instanceof Error ? activeError.message : "Failed to load compare data.";

  const compareDisplayName = useMemo(() => {
    if (effectiveBaseline === "target_user") {
      return selectedTargetName ?? "Selected user";
    }

    if (effectiveBaseline === "cohort") {
      return "Cohort average";
    }

    return "All players average";
  }, [effectiveBaseline, selectedTargetName]);

  const selectedMapIcon = getMapIconSrc(selectedMap);

  return {
    compareQuery,
    heroCompareQuery,
    heroesQuery,
    mapsQuery,
    tournamentsQuery,
    heroes,
    maps,
    tournaments,
    leftHero,
    rightHero,
    selectedMap,
    selectedMapIcon,
    selectedSubjectName,
    selectedTargetName,
    baselineSummary,
    rows,
    activeLoading,
    activeError,
    activeErrorMessage,
    compareDisplayName
  };
};
