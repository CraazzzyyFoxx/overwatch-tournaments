"use client";

import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { CardSurface } from "@/components/profile/atoms";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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
    <TableRow>
      <TableCell
        className="truncate px-3.5 py-2.5 text-caption font-medium text-[color:var(--aqt-fg)]"
        title={row.label}
      >
        {row.label}
      </TableCell>

      <TableCell
        className={`aqt-tnum px-3 py-2.5 text-right text-caption tabular-nums whitespace-nowrap ${winner === "left" ? "font-bold" : ""}`}
        style={leftValueStyle}
      >
        {formatMetricValue(row.subjectValue)}
      </TableCell>

      {/* Twin bars, mirrored around the column's centre line (where "vs" sits). */}
      <TableCell className="px-3 py-2.5">
        <div className="mx-auto flex w-full max-w-[260px] items-center gap-1.5">
          <div className="flex h-2.5 flex-1 justify-end overflow-hidden rounded-l-sm bg-[hsl(0_0%_100%/0.04)]">
            <div
              className={`h-full rounded-l-sm transition-all duration-500 motion-reduce:transition-none ${leftBarColor}`}
              style={{ width: `${leftPercent}%` }}
            />
          </div>
          <Separator orientation="vertical" className="h-2.5" />
          <div className="flex h-2.5 flex-1 justify-start overflow-hidden rounded-r-sm bg-[hsl(0_0%_100%/0.04)]">
            <div
              className={`h-full rounded-r-sm transition-all duration-500 motion-reduce:transition-none ${rightBarColor}`}
              style={{ width: `${rightPercent}%` }}
            />
          </div>
        </div>
      </TableCell>

      <TableCell
        className={`aqt-tnum px-3 py-2.5 text-left text-caption tabular-nums whitespace-nowrap ${winner === "right" ? "font-bold" : ""}`}
        style={rightValueStyle}
      >
        {formatMetricValue(row.baselineValue)}
      </TableCell>

      <TableCell className="px-3.5 py-2.5 text-right whitespace-nowrap">
        <TrendDelta
          delta={row.delta}
          deltaPercent={row.deltaPercent}
          betterWorse={row.betterWorse}
        />
      </TableCell>
    </TableRow>
  );
};

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

const UnifiedSkeleton = ({ isHeroScope }: { isHeroScope: boolean }) => {
  const rowCount = isHeroScope ? 6 : 8;

  return (
    <TableBody>
      {Array.from({ length: rowCount }).map((_, index) => (
        <TableRow key={`skeleton-row-${index}`} className="hover:bg-transparent">
          <TableCell className="px-3.5 py-2.5">
            <Skeleton className="h-4 w-40 max-w-full" />
          </TableCell>
          <TableCell className="px-3 py-2.5">
            <div className="flex justify-end">
              <Skeleton className="h-4 w-12" />
            </div>
          </TableCell>
          <TableCell className="px-3 py-2.5">
            <Skeleton className="mx-auto h-2.5 w-full max-w-[260px] rounded-sm" />
          </TableCell>
          <TableCell className="px-3 py-2.5">
            <Skeleton className="h-4 w-12" />
          </TableCell>
          <TableCell className="px-3.5 py-2.5">
            <div className="flex justify-end">
              <Skeleton className="h-4 w-16" />
            </div>
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  );
};

/* ------------------------------------------------------------------ */
/*  Column identity (header cell over each value column)               */
/* ------------------------------------------------------------------ */

/** Name over its own value column, mirrored: the subject reads toward the bars
 *  from the left, the baseline from the right. */
const ColumnIdentity = ({
  name,
  caption,
  hero,
  align
}: {
  name: string;
  caption: string;
  hero?: HeroInfo;
  align: "left" | "right";
}) => {
  const t = useTranslations();
  const durationUnits = {
    h: t("common.duration.h"),
    m: t("common.duration.m"),
    s: t("common.duration.s")
  };
  const heroName = hero?.name ?? t("users.compare.allHeroes");

  return (
    <div
      className={`flex min-w-0 items-center gap-2.5 ${align === "right" ? "flex-row-reverse text-right" : "text-left"}`}
    >
      {hero?.imagePath ? (
        <CatalogEntityImage
          entity={{ name: heroName, image_path: hero.imagePath }}
          size={36}
          rounded="lg"
          title={heroName}
        />
      ) : null}
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm font-semibold normal-case tracking-normal text-[color:var(--aqt-fg)]" title={name}>
          {name}
        </span>
        <span className="truncate text-label font-medium normal-case tracking-normal text-[color:var(--aqt-fg-muted)]">
          {hero ? heroName : caption}
        </span>
        {hero?.playtimeSeconds !== undefined ? (
          <span className="aqt-tnum truncate text-label font-medium normal-case tracking-normal text-[color:var(--aqt-fg-dim)]">
            {hero.playtimeLabel ?? t("users.compare.playtime")}:{" "}
            {formatDuration(hero.playtimeSeconds, durationUnits)}
          </span>
        ) : null}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Frame (card, columns, header row)                                  */
/* ------------------------------------------------------------------ */

const headBase = "aqt-tnum bg-[hsl(0_0%_100%/0.015)] py-3 align-bottom";

/** Shared by the table and its skeleton, so nothing moves when the rows land. */
const CompareTableFrame = ({
  subjectHead,
  baselineHead,
  children
}: {
  subjectHead: ReactNode;
  baselineHead: ReactNode;
  children: ReactNode;
}) => {
  const t = useTranslations();

  return (
    <CardSurface flush>
      <div
        className="overflow-x-auto"
        role="region"
        aria-label={t("users.compare.hero.title")}
        tabIndex={0}
      >
        {/* Fixed layout: every column keeps its width whatever the values, so
            the names in the header sit exactly over their numbers. */}
        <Table
          wrapperClassName="overflow-visible"
          className="aqt-tnum min-w-[920px] table-fixed border-collapse"
        >
          <colgroup>
            <col className="w-[22%]" />
            <col className="w-[20%]" />
            <col />
            <col className="w-[20%]" />
            <col className="w-[15%]" />
          </colgroup>
          <TableHeader>
            <TableRow>
              <TableHead className={`${headBase} px-3.5`}>{t("users.compare.colMetric")}</TableHead>
              <TableHead className={`${headBase} px-3`}>{subjectHead}</TableHead>
              <TableHead className={`${headBase} px-3 text-center`}>{t("common.vs")}</TableHead>
              <TableHead className={`${headBase} px-3`}>{baselineHead}</TableHead>
              <TableHead className={`${headBase} px-3.5 text-right`}>
                <abbr title={t("users.compare.colDeltaTitle")} className="no-underline">
                  {t("users.compare.colDelta")}
                </abbr>
              </TableHead>
            </TableRow>
          </TableHeader>
          {children}
        </Table>
      </div>
    </CardSurface>
  );
};

/** The table before the selection is checked: frame, unnamed columns, skeleton rows. */
export const CompareUnifiedTableSkeleton = ({ isHeroScope }: { isHeroScope: boolean }) => {
  const t = useTranslations();
  // `ColumnIdentity`'s lines, mirrored the same way: name, caption (hero in hero scope), playtime.
  const [subjectHead, baselineHead] = (["text-right", "text-left"] as const).map((align) => (
    <div key={align} className={`flex min-w-0 flex-col gap-0.5 ${align}`}>
      <span className="text-sm">
        <Skeleton variant="text" className="w-28 max-w-full" />
      </span>
      <span className="text-label">
        <Skeleton variant="text" className="w-20 max-w-full" />
      </span>
      {isHeroScope ? (
        <span className="text-label">
          <Skeleton variant="text" className="w-24 max-w-full" />
        </span>
      ) : null}
    </div>
  ));

  return (
    <div role="status" aria-busy="true">
      <span className="sr-only">{t("common.loading")}</span>
      <CompareTableFrame subjectHead={subjectHead} baselineHead={baselineHead}>
        <UnifiedSkeleton isHeroScope={isHeroScope} />
      </CompareTableFrame>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

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
  const hasRows = !loading && rows.length > 0;
  const showError = Boolean(errorMessage) && !hasRows;

  return (
    <div
      aria-busy={loading || refreshing}
      className={refreshing ? "opacity-70 transition-opacity" : "transition-opacity"}
    >
      <CompareTableFrame
        subjectHead={
          <ColumnIdentity
            name={subjectName}
            caption={t("users.compare.selectedUserColumn")}
            hero={isHeroScope ? subjectHero ?? {} : undefined}
            align="right"
          />
        }
        baselineHead={
          <ColumnIdentity
            name={baselineName}
            caption={
              isTargetBaseline ? t("users.compare.compareAgainst") : t("users.compare.baseline")
            }
            hero={isHeroScope ? baselineHero ?? {} : undefined}
            align="left"
          />
        }
      >
        {loading ? (
          <UnifiedSkeleton isHeroScope={isHeroScope} />
        ) : showError ? (
          <TableBody>
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={5}
                className="px-3.5 py-10 text-center text-sm text-[color:var(--aqt-rose)]"
              >
                <div className="flex flex-col items-center gap-3">
                  <span>{errorMessage}</span>
                  {onRetry ? (
                    <Button variant="outline" size="sm" onClick={onRetry}>
                      <RefreshCw aria-hidden />
                      {t("users.compare.retry")}
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          </TableBody>
        ) : !hasRows ? (
          <TableBody>
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={5}
                className="px-3.5 py-10 text-center text-sm text-[color:var(--aqt-fg-muted)]"
              >
                {t("users.compare.noMetrics")}
              </TableCell>
            </TableRow>
          </TableBody>
        ) : (
          <TableBody>
            {rows.map((row) => (
              <CompareMetricRow key={row.key} row={row} />
            ))}
          </TableBody>
        )}
      </CompareTableFrame>
    </div>
  );
};

export default CompareUnifiedTable;
