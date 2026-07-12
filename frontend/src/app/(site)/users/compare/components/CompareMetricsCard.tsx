"use client";

import Image from "next/image";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { Skeleton } from "@/components/ui/skeleton";
import { CompareRow } from "@/app/(site)/users/compare/types";
import { formatDuration, formatMetricValue, formatPercent } from "@/app/(site)/users/compare/utils";
import TrendDelta from "@/app/(site)/users/compare/components/TrendDelta";

interface CompareMetricsCardProps {
  mode: "subject" | "baseline";
  title: string;
  description: string;
  rows: CompareRow[];
  loading: boolean;
  errorMessage?: string;
  isHeroScope: boolean;
  heroName?: string;
  heroImagePath?: string;
  heroDominantColor?: string | null;
  playtimeSeconds?: number;
  playtimeLabel?: string;
}

const numHeader =
  "aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]";
const textHeader =
  "aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]";
const numCell = "aqt-mono px-3 py-2.5 text-right text-[13px] tabular-nums text-[color:var(--aqt-fg-muted)]";

const CompareMetricsSkeleton = ({ mode, isHeroScope }: { mode: "subject" | "baseline"; isHeroScope: boolean }) => {
  const rowCount = isHeroScope ? 6 : 8;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            <th className={textHeader}>Metric</th>
            {mode === "subject" ? <th className={numHeader}>Value</th> : null}
            {mode === "subject" && !isHeroScope ? <th className={numHeader}>Percentile</th> : null}
            {mode === "baseline" ? <th className={numHeader}>Baseline</th> : null}
            {mode === "baseline" ? <th className={numHeader}>Delta</th> : null}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rowCount }).map((_, index) => (
            <tr key={`skeleton-${mode}-${index}`} className="border-b border-[color:var(--aqt-border)] last:border-b-0">
              <td className="px-3 py-2.5">
                <Skeleton className="h-4 w-38" />
              </td>
              <td className="px-3 py-2.5">
                <div className="flex justify-end">
                  <Skeleton className="h-4 w-16" />
                </div>
              </td>
              {mode === "subject" && !isHeroScope ? (
                <td className="px-3 py-2.5">
                  <div className="flex justify-end">
                    <Skeleton className="h-4 w-14" />
                  </div>
                </td>
              ) : null}
              {mode === "baseline" ? (
                <td className="px-3 py-2.5">
                  <div className="flex justify-end">
                    <Skeleton className="h-4 w-20" />
                  </div>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const CompareMetricsCard = ({
  mode,
  title,
  description,
  rows,
  loading,
  errorMessage,
  isHeroScope,
  heroName,
  heroImagePath,
  playtimeSeconds,
  playtimeLabel = "Playtime"
}: CompareMetricsCardProps) => {
  return (
    <CardSurface
      className="relative min-h-125"
      title={title}
      subtitle={description}
      action={
        isHeroScope && heroImagePath ? (
          <Image
            src={heroImagePath}
            alt={heroName ?? "Hero"}
            width={44}
            height={44}
            className="h-11 w-11 rounded-md object-cover"
          />
        ) : undefined
      }
    >
      {isHeroScope ? (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-[color:var(--aqt-fg-muted)]">
          <span>Hero: {heroName ?? "All heroes"}</span>
          <span className="text-[color:var(--aqt-fg-faint)]">•</span>
          <span>
            {playtimeLabel}: {formatDuration(playtimeSeconds ?? 0)}
          </span>
        </div>
      ) : null}

      {loading ? (
        <CompareMetricsSkeleton mode={mode} isHeroScope={isHeroScope} />
      ) : errorMessage ? (
        <p className="text-sm text-[color:var(--aqt-rose)]">{errorMessage}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">No metrics available for current filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <th className={textHeader}>Metric</th>
                {mode === "subject" ? <th className={numHeader}>Value</th> : null}
                {mode === "subject" && !isHeroScope ? <th className={numHeader}>Percentile</th> : null}
                {mode === "baseline" ? <th className={numHeader}>Baseline</th> : null}
                {mode === "baseline" ? <th className={numHeader}>Delta</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={`${mode}-${row.key}`}
                  className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]"
                >
                  <td className="px-3 py-2.5 font-medium text-[color:var(--aqt-fg)]">{row.label}</td>

                  {mode === "subject" ? (
                    <td className={`${numCell} whitespace-nowrap text-[color:var(--aqt-fg)]`}>
                      {formatMetricValue(row.subjectValue)}
                    </td>
                  ) : null}

                  {mode === "subject" && !isHeroScope ? (
                    <td className={`${numCell} whitespace-nowrap`}>{formatPercent(row.percentile)}</td>
                  ) : null}

                  {mode === "baseline" ? (
                    <td className={`${numCell} whitespace-nowrap`}>{formatMetricValue(row.baselineValue)}</td>
                  ) : null}

                  {mode === "baseline" ? (
                    <td className="px-3 py-2.5 text-right whitespace-nowrap">
                      <TrendDelta
                        delta={row.delta}
                        deltaPercent={row.deltaPercent}
                        betterWorse={row.betterWorse}
                      />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CardSurface>
  );
};

export default CompareMetricsCard;
