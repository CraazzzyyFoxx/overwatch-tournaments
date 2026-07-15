"use client";

import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import HeroImage from "@/components/hero/HeroImage";
import { Skeleton } from "@/components/ui/skeleton";
import { CompareRow } from "@/app/(site)/users/compare/types";
import { formatDuration, formatMetricValue } from "@/app/(site)/users/compare/utils";
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
  refreshing?: boolean;
  errorMessage?: string;
  onRetry?: () => void;
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

/* Winner bar (emerald wash) vs neutral bar. */
const WINNER_BAR = "bg-[color:color-mix(in_srgb,var(--aqt-emerald)_55%,transparent)]";
const NEUTRAL_BAR = "bg-[hsl(0_0%_100%/0.14)]";

/* ------------------------------------------------------------------ */
/*  Metric row                                                         */
/* ------------------------------------------------------------------ */

const CompareMetricRow = ({ row }: { row: CompareRow }) => {
  const { leftPercent, rightPercent } = computeBarPercents(row.subjectValue, row.baselineValue);
  const winner = getRowWinner(row);

  const leftBarColor = winner === "left" ? WINNER_BAR : NEUTRAL_BAR;
  const rightBarColor = winner === "right" ? WINNER_BAR : NEUTRAL_BAR;

  const leftValueStyle =
    winner === "left" ? { color: "var(--aqt-emerald)" } : { color: "var(--aqt-fg)" };
  const rightValueStyle =
    winner === "right" ? { color: "var(--aqt-emerald)" } : { color: "var(--aqt-fg)" };

  return (
    <tr className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
      {/* Metric name */}
      <td
        className="px-3.5 py-2.5 text-[13.5px] font-medium text-[color:var(--aqt-fg)]"
        title={row.label}
      >
        {row.label}
      </td>

      {/* Subject value */}
      <td
        className={`aqt-mono px-2 py-2.5 text-right text-[13px] tabular-nums whitespace-nowrap ${winner === "left" ? "font-bold" : ""}`}
        style={leftValueStyle}
      >
        {formatMetricValue(row.subjectValue)}
      </td>

      {/* Twin bars */}
      <td className="px-2 py-2.5">
        <div className="mx-auto flex w-full min-w-[140px] max-w-[240px] items-center gap-1.5">
          <div className="flex h-2.5 flex-1 justify-end overflow-hidden rounded-l-sm bg-[hsl(0_0%_100%/0.04)]">
            <div
              className={`h-full rounded-l-sm transition-all duration-500 ${leftBarColor}`}
              style={{ width: `${leftPercent}%` }}
            />
          </div>
          <div className="h-2.5 w-px shrink-0 bg-[color:var(--aqt-border)]" />
          <div className="flex h-2.5 flex-1 justify-start overflow-hidden rounded-r-sm bg-[hsl(0_0%_100%/0.04)]">
            <div
              className={`h-full rounded-r-sm transition-all duration-500 ${rightBarColor}`}
              style={{ width: `${rightPercent}%` }}
            />
          </div>
        </div>
      </td>

      {/* Baseline value */}
      <td
        className={`aqt-mono px-2 py-2.5 text-left text-[13px] tabular-nums whitespace-nowrap ${winner === "right" ? "font-bold" : ""}`}
        style={rightValueStyle}
      >
        {formatMetricValue(row.baselineValue)}
      </td>

      {/* Delta */}
      <td className="px-3.5 py-2.5 text-right whitespace-nowrap">
        <TrendDelta
          delta={row.delta}
          deltaPercent={row.deltaPercent}
          betterWorse={row.betterWorse}
        />
      </td>
    </tr>
  );
};

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

const UnifiedSkeleton = ({ isHeroScope }: { isHeroScope: boolean }) => {
  const rowCount = isHeroScope ? 6 : 8;

  return (
    <tbody>
      {Array.from({ length: rowCount }).map((_, index) => (
        <tr
          key={`skeleton-row-${index}`}
          className="border-b border-[color:var(--aqt-border)] last:border-b-0"
        >
          <td className="px-3.5 py-2.5">
            <Skeleton className="h-4 w-40" />
          </td>
          <td className="px-2 py-2.5">
            <div className="flex justify-end">
              <Skeleton className="h-4 w-12" />
            </div>
          </td>
          <td className="px-2 py-2.5">
            <Skeleton className="mx-auto h-2.5 w-full min-w-[140px] max-w-[240px] rounded-sm" />
          </td>
          <td className="px-2 py-2.5">
            <Skeleton className="h-4 w-12" />
          </td>
          <td className="px-3.5 py-2.5">
            <div className="flex justify-end">
              <Skeleton className="h-4 w-16" />
            </div>
          </td>
        </tr>
      ))}
    </tbody>
  );
};

/* ------------------------------------------------------------------ */
/*  Identity band                                                      */
/* ------------------------------------------------------------------ */

const HeroBadge = ({
  hero,
  label,
  align
}: {
  hero: HeroInfo;
  label: string;
  align: "left" | "right";
}) => {
  const t = useTranslations();
  const durationUnits = {
    h: t("users.compare.durationH"),
    m: t("users.compare.durationM"),
    s: t("users.compare.durationS")
  };

  return (
    <div
      className={`flex items-center gap-3 ${align === "right" ? "flex-row-reverse text-right" : ""}`}
    >
      {hero.imagePath ? (
        <HeroImage
          hero={{
            name: hero.name ?? t("users.compare.allHeroes"),
            image_path: hero.imagePath,
            role: ""
          }}
          size={44}
          rounded="lg"
          title={hero.name ?? t("users.compare.allHeroes")}
        />
      ) : null}
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold text-[color:var(--aqt-fg)]">{label}</span>
        <span className="text-xs text-[color:var(--aqt-fg-muted)]">
          {hero.name ?? t("users.compare.allHeroes")}
        </span>
        {hero.playtimeSeconds !== undefined ? (
          <span className="aqt-mono text-[10px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-dim)]">
            {hero.playtimeLabel ?? t("users.compare.playtime")}:{" "}
            {formatDuration(hero.playtimeSeconds, durationUnits)}
          </span>
        ) : null}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

const headBase =
  "aqt-mono border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-3.5 py-3 text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]";

const CompareUnifiedTable = ({
  subjectName,
  baselineName,
  rows,
  loading,
  refreshing = false,
  errorMessage,
  onRetry,
  isHeroScope,
  isTargetBaseline,
  subjectHero,
  baselineHero
}: CompareUnifiedTableProps) => {
  const t = useTranslations();
  const rightLabel = isTargetBaseline ? baselineName : t("users.compare.baseline");
  const hasRows = !loading && rows.length > 0;
  const showError = Boolean(errorMessage) && !hasRows;

  return (
    <div
      aria-busy={loading || refreshing}
      className={refreshing ? "opacity-70 transition-opacity" : "transition-opacity"}
    >
      <CardSurface flush>
        {/* Identity band: subject vs baseline */}
        <div className="flex items-center gap-3 border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-[18px] py-4">
          {isHeroScope ? (
            <div className="flex w-full items-center justify-between gap-3">
              <HeroBadge hero={subjectHero ?? {}} label={subjectName} align="left" />
              <span className="aqt-mono shrink-0 text-[11px] font-bold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
                {t("common.vs")}
              </span>
              <HeroBadge hero={baselineHero ?? {}} label={baselineName} align="right" />
            </div>
          ) : (
            <div className="flex w-full items-center justify-between gap-3">
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold text-[color:var(--aqt-fg)]">
                  {subjectName}
                </span>
                <span className="aqt-mono text-[10px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-dim)]">
                  {t("users.compare.selectedUserColumn")}
                </span>
              </div>
              <span className="aqt-mono shrink-0 text-[11px] font-bold uppercase tracking-[0.18em] text-[color:var(--aqt-fg-dim)]">
                {t("common.vs")}
              </span>
              <div className="flex flex-col items-end gap-0.5 text-right">
                <span className="text-sm font-semibold text-[color:var(--aqt-fg)]">
                  {baselineName}
                </span>
                <span className="aqt-mono text-[10px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-dim)]">
                  {isTargetBaseline
                    ? t("users.compare.compareAgainst")
                    : t("users.compare.baseline")}
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="aqt-tnum w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <th className={`${headBase} text-left`}>{t("users.compare.colMetric")}</th>
                <th className={`${headBase} text-right`}>{subjectName}</th>
                <th className={`${headBase} text-center`} aria-hidden />
                <th className={`${headBase} text-left`}>{rightLabel}</th>
                <th className={`${headBase} text-right`}>{t("users.compare.colDelta")}</th>
              </tr>
            </thead>

            {loading ? (
              <UnifiedSkeleton isHeroScope={isHeroScope} />
            ) : showError ? (
              <tbody>
                <tr>
                  <td
                    colSpan={5}
                    className="px-3.5 py-10 text-center text-sm text-[color:var(--aqt-rose)]"
                  >
                    <div className="flex flex-col items-center gap-3">
                      <span>{errorMessage}</span>
                      {onRetry ? (
                        <button
                          type="button"
                          onClick={onRetry}
                          className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-[color:var(--aqt-border)] px-3 text-xs font-semibold text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)]"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          {t("users.compare.retry")}
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              </tbody>
            ) : !hasRows ? (
              <tbody>
                <tr>
                  <td
                    colSpan={5}
                    className="px-3.5 py-10 text-center text-sm text-[color:var(--aqt-fg-muted)]"
                  >
                    {t("users.compare.noMetrics")}
                  </td>
                </tr>
              </tbody>
            ) : (
              <tbody>
                {rows.map((row) => (
                  <CompareMetricRow key={row.key} row={row} />
                ))}
              </tbody>
            )}
          </table>
        </div>
      </CardSurface>
    </div>
  );
};

export default CompareUnifiedTable;
