import { UserCompareBaselineMode } from "@/types/user.types";

export type CompareScope = "overall" | "hero";

export interface CompareRow {
  key: string;
  label: string;
  subjectValue: number | null;
  baselineValue: number | null;
  delta: number | null;
  deltaPercent: number | null;
  percentile: number | null;
  betterWorse?: "better" | "worse" | "equal" | null;
  higherIsBetter?: boolean;
}

export interface ParsedCompareParams {
  subjectUserId?: number;
  targetUserId?: number;
  role?: "Tank" | "Damage" | "Support";
  divMin?: number;
  divMax?: number;
  tournamentId?: number;
  leftHeroId?: number;
  rightHeroId?: number;
  mapId?: number;
  scope: CompareScope;
}

export interface CompareBaselineState {
  isHeroScope: boolean;
  isTargetBaseline: boolean;
  hasCohortFilters: boolean;
  effectiveBaseline: UserCompareBaselineMode;
}
