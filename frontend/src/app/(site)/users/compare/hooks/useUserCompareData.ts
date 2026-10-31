"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import tournamentService from "@/services/tournament.service";
import userService from "@/services/user.service";
import { UserCompareBaselineMode } from "@/types/user.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { CompareRow } from "@/app/(site)/users/compare/types";
import { compareRoleFilter, getMapIconSrc, normalizeNumber } from "@/app/(site)/users/compare/utils";
import {
  buildHeroCompareQueryOptions,
  buildOverallCompareQueryOptions,
  getCompareActivity,
  shouldLoadHeroCatalogs
} from "@/app/(site)/users/compare/hooks/compare-query-options";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { useCatalogEntities, useCatalogSelection } from "@/hooks/useCatalogEntities";
import { useCurrentWorkspaceId, useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { divisionRangeEnds } from "@/components/DivisionRangePicker";
import { useRoleName } from "@/hooks/useRoleName";
import { findRole } from "@/lib/roster/ontology";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";

interface UseUserCompareDataParams {
  isHeroScope: boolean;
  subjectUserId?: number;
  effectiveBaseline: UserCompareBaselineMode;
  targetUserId?: number;
  /** A rated role code of the browsed game (`?role=`). */
  role?: string;
  divMin?: number;
  divMax?: number;
  tournamentId?: number;
  leftHeroId?: number;
  rightHeroId?: number;
  mapId?: number;
  scope: StatsScope;
  /** The resolved browsing game; `null` while unresolved or invalid — no catalog is read then. */
  discipline: string | null;
  /** The browsed game's metadata: its per-character stat vocabulary (and native ladder for all communities). */
  metadata: DisciplineMetadata | null;
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
  mapId,
  scope,
  discipline,
  metadata
}: UseUserCompareDataParams) => {
  const t = useTranslations();

  // One workspace for everything the page asks: the backend resolves both the
  // division grid and the population from it, so the picker's tiers must come
  // from the same place. All communities read the reference grid.
  const currentWorkspaceId = useCurrentWorkspaceId();
  const workspaceGrid = useDivisionGrid(discipline ?? undefined);
  const workspaceId: WorkspaceAxis | undefined = scope === "all" ? "all" : (currentWorkspaceId ?? undefined);
  // All communities read the game's own native ladder (none → no division bounds), never another game's.
  const divisionGrid = useMemo(
    () => (scope === "all" ? { tiers: [...(metadata?.native_ladder ?? [])] } : workspaceGrid),
    [scope, metadata, workspaceGrid]
  );
  // A character comparison compares per-character observations: the game's active stats, without its team-level
  // (`group: "team"`) ones, which no character carries, and the internal impact breakdown (`group: "impact"`). No
  // vocabulary → no comparison is requested.
  const stats = useMemo(
    () =>
      (metadata?.stat_defs ?? [])
        .filter((def) => def.active && def.group !== "team" && def.group !== "impact")
        .map((def) => def.code),
    [metadata]
  );

  // A cohort role resolves against the game's own ontology; a read naming one waits for it rather than running wide.
  const roleFilter = useMemo(() => compareRoleFilter(metadata, role), [metadata, role]);
  const roleReady = role === undefined || metadata !== null;
  const nameOf = useRoleName();

  const overallOptions = buildOverallCompareQueryOptions({
    isHeroScope,
    subjectUserId,
    discipline,
    baseline: effectiveBaseline,
    targetUserId,
    role: roleFilter,
    divMin,
    divMax,
    tournamentId,
    workspaceId,
    fetchCompare: userService.getUserCompare
  });
  // A game without a grid on this axis refuses the comparison; the page shows `MissingGridNotice` for it.
  const compareQuery = useQuery({
    ...overallOptions,
    enabled: overallOptions.enabled && roleReady,
    meta: { rendersGridRefusal: true }
  });

  const heroesQuery = useCatalogEntities(discipline, "character", {
    enabled: shouldLoadHeroCatalogs(isHeroScope)
  });
  const mapsQuery = useCatalogEntities(discipline, "map", { enabled: shouldLoadHeroCatalogs(isHeroScope) });

  // Ids come from the URL: each must belong to this game's catalog before anything is requested for it (§3.4).
  const checkSelections = shouldLoadHeroCatalogs(isHeroScope);
  const leftSelection = useCatalogSelection(discipline, "character", leftHeroId, { enabled: checkSelections });
  const rightSelection = useCatalogSelection(discipline, "character", rightHeroId, { enabled: checkSelections });
  const mapSelection = useCatalogSelection(discipline, "map", mapId, { enabled: checkSelections });
  const selections = [leftSelection, rightSelection, mapSelection];
  const selectionInvalid = selections.some((selection) => selection.status === "invalid");
  // Statistics are shown only for selections that were CHECKED valid: pending, invalid and failed checks all withhold
  // them, so another game's cached results never stand in while the scoped lookup is out.
  const selectionsSettled = selections.every((selection) => selection.status === "none" || selection.status === "valid");
  const selectionError = selections.some((selection) => selection.status === "error");
  const selectionPending = selections.some((selection) => selection.status === "loading");
  const retrySelections = () => {
    for (const selection of selections) if (selection.status === "error") selection.refetch();
  };

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.selectOptions(workspaceId ?? null),
    queryFn: () => tournamentService.getAll(null, workspaceId ?? null),
    staleTime: 5 * 60 * 1000
  });

  const heroCompareOptions = buildHeroCompareQueryOptions({
      isHeroScope,
      subjectUserId,
      discipline,
      baseline: effectiveBaseline,
      targetUserId,
      role: roleFilter,
      divMin,
      divMax,
      tournamentId,
      workspaceId,
      leftEntityId: leftHeroId,
      rightEntityId: rightHeroId,
      mapId,
      stats,
      fetchCompare: userService.getUserCharacterCompare
    });
  const heroCompareQuery = useQuery({
    ...heroCompareOptions,
    enabled: heroCompareOptions.enabled && selectionsSettled && stats.length > 0 && roleReady,
    meta: { rendersGridRefusal: true }
  });

  const heroes = heroesQuery.data ?? [];
  const maps = mapsQuery.data ?? [];
  const tournaments = tournamentsQuery.data?.results ?? [];

  const leftHero = leftSelection.entity ?? undefined;
  const rightHero = rightSelection.entity ?? undefined;
  const selectedMap = mapSelection.entity ?? undefined;

  const heroCompareData = selectionsSettled ? heroCompareQuery.data : undefined;
  const selectedSubjectName = compareQuery.data?.subject.name ?? heroCompareData?.subject.name;
  const selectedTargetName = compareQuery.data?.baseline.target_user?.name ?? heroCompareData?.target?.name;

  const baselineSummary = useMemo(() => {
    if (effectiveBaseline === "target_user") {
      return selectedTargetName
        ? t("users.compare.comparingAgainstUser", { name: selectedTargetName })
        : t("users.compare.comparingAgainstSelected");
    }

    if (effectiveBaseline === "cohort") {
      const roleNode = roleFilter && metadata ? findRole(metadata, roleFilter) : null;
      const roleText = roleNode ? nameOf(roleNode) : t("users.compare.allRoles");
      const rangeText =
        divisionRangeEnds(divisionGrid, divMin, divMax)
          .map((tier) => tier.name)
          .join(" – ") || t("common.any");
      return t("users.compare.comparingAgainstCohort", { role: roleText, range: rangeText });
    }

    return t("users.compare.comparingAgainstGlobal");
  }, [effectiveBaseline, selectedTargetName, roleFilter, metadata, nameOf, divMin, divMax, divisionGrid, t]);

  const rows = useMemo<CompareRow[]>(() => {
    if (isHeroScope) {
      // A conflicting selection has no results: a previous selection's data is never shown for it.
      if (!heroCompareData) return [];
      return heroCompareData.metrics.map((metric) => ({
        key: metric.stat,
        label: metadata?.stat_defs.find((def) => def.code === metric.stat)?.name ?? metric.stat,
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
  }, [isHeroScope, compareQuery.data, heroCompareData, metadata]);

  const activeLoading = isHeroScope ? heroCompareQuery.isLoading : compareQuery.isLoading;
  const activeFetching = isHeroScope ? heroCompareQuery.isFetching : compareQuery.isFetching;
  const { isRefreshing: activeRefreshing } = getCompareActivity({
    isLoading: activeLoading,
    isFetching: activeFetching
  });
  const activeError = isHeroScope ? heroCompareQuery.error : compareQuery.error;
  const activeErrorMessage =
    activeError instanceof Error ? activeError.message : t("users.compare.loadError");

  const compareDisplayName = useMemo(() => {
    if (effectiveBaseline === "target_user") {
      return selectedTargetName ?? t("users.compare.selectedUser");
    }

    if (effectiveBaseline === "cohort") {
      return t("users.compare.cohortAverage");
    }

    return t("users.compare.allPlayersAverage");
  }, [effectiveBaseline, selectedTargetName, t]);

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
    activeRefreshing,
    activeError,
    activeErrorMessage,
    compareDisplayName,
    divisionGrid,
    /** The workspace every read on the page is pinned to, or the cross-workspace sentinel. */
    workspaceId,
    /** An id in the URL that is not in the scoped discipline's catalog: show it, request and render nothing. */
    selectionInvalid,
    selectionsSettled,
    selectionError,
    selectionPending,
    retrySelections
  };
};
