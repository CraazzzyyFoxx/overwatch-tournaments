"use client";

import { Badge } from "@/components/ui/badge";
import { UserCompareBaselineMode } from "@/types/user.types";

interface CompareSummaryBadgesProps {
  effectiveBaseline: UserCompareBaselineMode;
  baselineSummary: string;
  isHeroScope: boolean;
  selectedMapName?: string;
}

const CompareSummaryBadges = ({
  effectiveBaseline,
  baselineSummary,
  isHeroScope,
  selectedMapName
}: CompareSummaryBadgesProps) => {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant="outline">Baseline: {effectiveBaseline.replace("_", " ")}</Badge>
      <Badge variant="outline">{baselineSummary}</Badge>
      {isHeroScope && selectedMapName ? <Badge variant="outline">Map: {selectedMapName}</Badge> : null}
    </div>
  );
};

export default CompareSummaryBadges;
