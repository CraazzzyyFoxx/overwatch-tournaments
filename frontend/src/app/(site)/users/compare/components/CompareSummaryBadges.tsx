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
  const badgeClass =
    "aqt-mono border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)]";

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant="outline" className={badgeClass}>
        Baseline: {effectiveBaseline.replace("_", " ")}
      </Badge>
      <Badge variant="outline" className={badgeClass}>
        {baselineSummary}
      </Badge>
      {isHeroScope && selectedMapName ? (
        <Badge variant="outline" className={badgeClass}>
          Map: {selectedMapName}
        </Badge>
      ) : null}
    </div>
  );
};

export default CompareSummaryBadges;
