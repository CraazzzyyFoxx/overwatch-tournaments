"use client";

import Image from "next/image";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CompareRow } from "@/app/(site)/users/compare/types";
import { formatDuration, formatMetricValue, formatPercent, getGlowVarsFromColor } from "@/app/(site)/users/compare/utils";
import GlassGlow from "@/app/(site)/users/compare/components/GlassGlow";
import TrendDelta from "@/app/(site)/users/compare/components/TrendDelta";

interface HeroInfo {
  name?: string;
  imagePath?: string;
  dominantColor?: string | null;
  playtimeSeconds?: number;
  playtimeLabel?: string;
}

interface CompareUnifiedTableProps {
  subjectName: string;
  baselineName: string;
  rows: CompareRow[];
  loading: boolean;
  errorMessage?: string;
  isHeroScope: boolean;
  isTargetBaseline: boolean;
  subjectHero?: HeroInfo;
  baselineHero?: HeroInfo;
}

/* ------------------------------------------------------------------ */
/*  Bar ratio helper                                                   */
/* ------------------------------------------------------------------ */

const MIN_BAR_PERCENT = 8;

const computeBarPercents = (
  a: number | null,
  b: number | null
): { leftPercent: number; rightPercent: number } => {
  const safeA = a !== null && Number.isFinite(a) ? Math.abs(a) : 0;
  const safeB = b !== null && Number.isFinite(b) ? Math.abs(b) : 0;
  const max = Math.max(safeA, safeB);

  if (max === 0) return { leftPercent: 50, rightPercent: 50 };

  let leftPercent = (safeA / max) * 100;
  let rightPercent = (safeB / max) * 100;

  if (leftPercent > 0 && leftPercent < MIN_BAR_PERCENT) leftPercent = MIN_BAR_PERCENT;
  if (rightPercent > 0 && rightPercent < MIN_BAR_PERCENT) rightPercent = MIN_BAR_PERCENT;

  return { leftPercent, rightPercent };
};

const getRowWinner = (row: CompareRow): "left" | "right" | "tie" => {
  if (row.betterWorse === "better") return "left";
  if (row.betterWorse === "worse") return "right";
  return "tie";
};

/* ------------------------------------------------------------------ */
/*  Metric row                                                         */
/* ------------------------------------------------------------------ */

const CompareMetricRow = ({
  row,
  showPercentile
}: {
  row: CompareRow;
  showPercentile: boolean;
}) => {
  const { leftPercent, rightPercent } = computeBarPercents(row.subjectValue, row.baselineValue);
  const winner = getRowWinner(row);

  const leftBarColor =
    winner === "left"
      ? "bg-emerald-500/60"
      : winner === "tie"
        ? "bg-zinc-500/40"
        : "bg-zinc-500/30";

  const rightBarColor =
    winner === "right"
      ? "bg-emerald-500/60"
      : winner === "tie"
        ? "bg-zinc-500/40"
        : "bg-zinc-500/30";

  const leftValueClass = winner === "left" ? "text-emerald-400 font-semibold" : "text-foreground";
  const rightValueClass = winner === "right" ? "text-emerald-400 font-semibold" : "text-foreground";

  return (
    <div className="group flex items-center gap-3 rounded-lg px-3 py-3 transition-colors hover:bg-muted/20">
      {/* Metric name */}
      <span className="w-52 shrink-0 truncate text-base font-medium text-foreground" title={row.label}>
        {row.label}
      </span>

      {/* Bars */}
      <div className="mx-auto flex w-full max-w-200 items-center gap-2">
        {/* Left value */}
        <span className={`w-18 shrink-0 text-right text-sm tabular-nums ${leftValueClass}`}>
          {formatMetricValue(row.subjectValue)}
        </span>

        {/* Left bar (grows right-to-left) */}
        <div className="flex h-3.5 flex-1 justify-end overflow-hidden rounded-l-sm bg-muted/15">
          <div
            className={`h-full rounded-l-sm transition-all duration-500 ${leftBarColor}`}
            style={{ width: `${leftPercent}%` }}
          />
        </div>

        {/* Divider */}
        <div className="h-3.5 w-px shrink-0 bg-border/60" />

        {/* Right bar (grows left-to-right) */}
        <div className="flex h-3.5 flex-1 justify-start overflow-hidden rounded-r-sm bg-muted/15">
          <div
            className={`h-full rounded-r-sm transition-all duration-500 ${rightBarColor}`}
            style={{ width: `${rightPercent}%` }}
          />
        </div>

        {/* Right value */}
        <span className={`w-26 shrink-0 text-left text-sm tabular-nums ${rightValueClass}`}>
          {formatMetricValue(row.baselineValue)}
        </span>
      </div>

      {/* Delta + percentile */}
      <div className="flex w-44 shrink-0 items-center justify-end gap-1.5">
        {showPercentile && row.percentile !== null ? (
          <span className="text-sm tabular-nums text-muted-foreground/70">
            {formatPercent(row.percentile)}
          </span>
        ) : null}
        <TrendDelta
          delta={row.delta}
          deltaPercent={row.deltaPercent}
          betterWorse={row.betterWorse}
        />
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

const UnifiedSkeleton = ({ isHeroScope }: { isHeroScope: boolean }) => {
  const rowCount = isHeroScope ? 6 : 8;

  return (
    <div className="space-y-0.5">
      {Array.from({ length: rowCount }).map((_, index) => (
        <div key={`skeleton-row-${index}`} className="flex items-center gap-3 rounded-lg px-3 py-1.5">
          <Skeleton className="h-4 w-52 shrink-0" />
          <div className="mx-auto flex w-full max-w-sm items-center gap-2">
            <Skeleton className="h-3.5 w-18 shrink-0" />
            <div className="flex h-3.5 flex-1 justify-end">
              <Skeleton className="h-3.5 w-3/4 rounded-l-sm" />
            </div>
            <div className="h-3.5 w-px bg-border/60" />
            <div className="flex h-3.5 flex-1 justify-start">
              <Skeleton className="h-3.5 w-2/3 rounded-r-sm" />
            </div>
            <Skeleton className="h-3.5 w-18 shrink-0" />
          </div>
          <Skeleton className="h-4 w-44 shrink-0" />
        </div>
      ))}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Header badges                                                      */
/* ------------------------------------------------------------------ */

const HeroBadge = ({ hero, label, align }: { hero: HeroInfo; label: string; align: "left" | "right" }) => (
  <div className={`flex items-center gap-3 ${align === "right" ? "flex-row-reverse text-right" : ""}`}>
    {hero.imagePath ? (
      <Image
        src={hero.imagePath}
        alt={hero.name ?? "Hero"}
        width={48}
        height={48}
        className="h-12 w-12 rounded-md object-cover"
      />
    ) : null}
    <div className="flex flex-col gap-0.5">
      <span className="text-sm font-medium">{label}</span>
      <span className="text-xs text-muted-foreground">{hero.name ?? "All heroes"}</span>
      {hero.playtimeSeconds !== undefined ? (
        <span className="text-xs text-muted-foreground">
          {hero.playtimeLabel ?? "Playtime"}: {formatDuration(hero.playtimeSeconds)}
        </span>
      ) : null}
    </div>
  </div>
);

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

const CompareUnifiedTable = ({
  subjectName,
  baselineName,
  rows,
  loading,
  errorMessage,
  isHeroScope,
  isTargetBaseline,
  subjectHero,
  baselineHero
}: CompareUnifiedTableProps) => {
  const subjectGlow = isHeroScope ? getGlowVarsFromColor(subjectHero?.dominantColor) : null;
  const baselineGlow = isHeroScope ? getGlowVarsFromColor(baselineHero?.dominantColor) : null;

  const glowVars = subjectGlow ?? baselineGlow;
  const showPercentile = !isHeroScope;
  const rightLabel = isTargetBaseline ? baselineName : "Baseline";

  return (
    <Card className="relative overflow-hidden" style={glowVars ? (glowVars as React.CSSProperties) : undefined}>
      <GlassGlow />

      <CardHeader className="relative pb-3">
        {isHeroScope ? (
          <div className="flex items-center gap-3 px-3">
            <div className="flex w-52 shrink-0 justify-start">
              <HeroBadge hero={subjectHero ?? {}} label={subjectName} align="left" />
            </div>
            <div className="mx-auto flex w-full max-w-200 items-center gap-2">
              <span className="w-18 shrink-0" />
              <div className="flex-1" />
              <span className="shrink-0 text-xs font-semibold tracking-widest uppercase text-muted-foreground">vs</span>
              <div className="flex-1" />
              <span className="w-18 shrink-0" />
            </div>
            <div className="flex w-52 shrink-0 justify-end">
              <HeroBadge hero={baselineHero ?? {}} label={baselineName} align="right" />
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 px-3">
            <div className="flex w-52 shrink-0 flex-col gap-0.5">
              <span className="text-sm font-medium">{subjectName}</span>
              <span className="text-xs text-muted-foreground">Selected User</span>
            </div>
            <div className="mx-auto flex w-full max-w-200 items-center gap-2">
              <span className="w-18 shrink-0" />
              <div className="flex-1" />
              <span className="shrink-0 text-xs font-semibold tracking-widest uppercase text-muted-foreground">vs</span>
              <div className="flex-1" />
              <span className="w-18 shrink-0" />
            </div>
            <div className="flex w-44 shrink-0 flex-col items-end gap-0.5">
              <span className="text-sm font-medium">{baselineName}</span>
              <span className="text-xs text-muted-foreground">{isTargetBaseline ? "Compare against" : "Baseline"}</span>
            </div>
          </div>
        )}
      </CardHeader>

      <CardContent className="relative">
        {/* Column labels */}
        {!loading && !errorMessage && rows.length > 0 ? (
          <div className="mb-0.5 flex items-center gap-3 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <span className="w-52 shrink-0" />
            <div className="mx-auto flex w-full max-w-200 items-center gap-2">
              <span className="relative w-18 shrink-0">
                <span className="absolute right-0 top-1/2 -translate-y-1/2 whitespace-nowrap">{subjectName}</span>
              </span>
              <div className="flex-1" />
              <div className="w-px shrink-0" />
              <div className="flex-1" />
              <span className="relative w-26 shrink-0">
                <span className="absolute left-0 top-1/2 -translate-y-1/2 whitespace-nowrap">{rightLabel}</span>
              </span>
            </div>
            <span className="w-44 shrink-0" />
          </div>
        ) : null}

        {loading ? (
          <UnifiedSkeleton isHeroScope={isHeroScope} />
        ) : errorMessage ? (
          <p className="text-sm text-destructive">{errorMessage}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No metrics available for current filters.</p>
        ) : (
          <div className="divide-y divide-border/30">
            {rows.map((row) => (
              <CompareMetricRow key={row.key} row={row} showPercentile={false} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default CompareUnifiedTable;
