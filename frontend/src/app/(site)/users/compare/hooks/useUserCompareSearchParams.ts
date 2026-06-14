"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ParsedCompareParams, CompareBaselineState } from "@/app/(site)/users/compare/types";
import { UserCompareBaselineMode } from "@/types/user.types";
import { parseOptionalInt, parseRole, parseScope } from "@/app/(site)/users/compare/utils";

export type CompareParamUpdates = Record<string, string | number | undefined>;

export interface UseUserCompareSearchParamsResult extends ParsedCompareParams, CompareBaselineState {
  updateParams: (updates: CompareParamUpdates) => void;
}

export const useUserCompareSearchParams = (): UseUserCompareSearchParamsResult => {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const searchParamsString = searchParams.toString();

  const subjectUserId = parseOptionalInt(searchParams.get("user_id"));
  const targetUserId = parseOptionalInt(searchParams.get("target_user_id"));
  const role = parseRole(searchParams.get("role"));
  const divMin = parseOptionalInt(searchParams.get("div_min"));
  const divMax = parseOptionalInt(searchParams.get("div_max"));
  const tournamentId = parseOptionalInt(searchParams.get("tournament_id"));
  const leftHeroId = parseOptionalInt(searchParams.get("left_hero_id"));
  const rightHeroId = parseOptionalInt(searchParams.get("right_hero_id"));
  const mapId = parseOptionalInt(searchParams.get("map_id"));
  const scope = parseScope(searchParams.get("scope"));

  const updateParams = useCallback(
    (updates: CompareParamUpdates): void => {
      const next = new URLSearchParams(searchParamsString);

      Object.entries(updates).forEach(([key, value]) => {
        if (value === undefined || value === "") {
          next.delete(key);
          return;
        }

        next.set(key, String(value));
      });

      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname);
    },
    [pathname, router, searchParamsString]
  );

  const isHeroScope = scope === "hero";
  const isTargetBaseline = typeof targetUserId === "number" && targetUserId > 0;
  const hasCohortFilters = Boolean(role || divMin || divMax);
  const effectiveBaseline: UserCompareBaselineMode = isTargetBaseline
    ? "target_user"
    : hasCohortFilters
      ? "cohort"
      : "global";

  return {
    subjectUserId,
    targetUserId,
    role,
    divMin,
    divMax,
    tournamentId,
    leftHeroId,
    rightHeroId,
    mapId,
    scope,
    isHeroScope,
    isTargetBaseline,
    hasCohortFilters,
    effectiveBaseline,
    updateParams
  };
};
