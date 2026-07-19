import type { CompareScope } from "@/app/(site)/users/compare/types";
import type { UserCompareBaselineMode } from "@/types/user.types";

interface ComparePageHeroModelInput {
  hasSubject: boolean;
  hasData: boolean;
  isLoading: boolean;
  scope: CompareScope;
  baseline: UserCompareBaselineMode;
  sampleSize?: number;
  metricCount: number;
}

export interface ComparePageHeroModel {
  scope: CompareScope;
  baseline: UserCompareBaselineMode;
  sampleSize: number | "—";
  metricCount: number | "—";
}

export const getComparePageHeroModel = ({
  hasSubject,
  hasData,
  isLoading,
  scope,
  baseline,
  sampleSize,
  metricCount
}: ComparePageHeroModelInput): ComparePageHeroModel => {
  const dataReady = hasSubject && hasData && !isLoading;

  return {
    scope,
    baseline,
    sampleSize: dataReady && sampleSize !== undefined ? sampleSize : "—",
    metricCount: dataReady ? metricCount : "—"
  };
};
