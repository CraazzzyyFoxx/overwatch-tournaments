"use client";

import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { formatMetricValue, formatPercent } from "@/app/(site)/users/compare/utils";

interface TrendDeltaProps {
  delta: number | null;
  deltaPercent: number | null;
  betterWorse?: "better" | "worse" | "equal" | null;
}

const TrendDelta = ({ delta, deltaPercent, betterWorse }: TrendDeltaProps) => {
  if (delta === null || !Number.isFinite(delta)) {
    return <span className="text-muted-foreground">-</span>;
  }

  if (betterWorse === null || betterWorse === undefined) {
    return <span className="text-muted-foreground">-</span>;
  }

  if (betterWorse === "equal") {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-zinc-400">
        <Minus className="h-4 w-4" aria-hidden />
        <span className="tabular-nums">
          {formatMetricValue(delta)}
          {deltaPercent !== null ? ` (${formatPercent(deltaPercent)})` : ""}
        </span>
      </span>
    );
  }

  const isBetter = betterWorse === "better";
  const Icon = isBetter ? TrendingUp : TrendingDown;
  const deltaClass = isBetter ? "text-emerald-400" : "text-rose-400";

  return (
    <span className={`inline-flex items-center gap-1 text-sm ${deltaClass}`}>
      <Icon className="h-4 w-4" aria-hidden />
      <span className="tabular-nums">
        {formatMetricValue(delta)}
        {deltaPercent !== null ? ` (${formatPercent(deltaPercent)})` : ""}
      </span>
    </span>
  );
};

export default TrendDelta;
