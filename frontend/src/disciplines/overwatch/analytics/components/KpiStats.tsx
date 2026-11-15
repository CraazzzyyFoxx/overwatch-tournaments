"use client";

import { useTranslations } from "next-intl";

import { HeroStat } from "@/components/site/PageHero";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useFormatter } from "@/lib/datetime/client";
import type { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";
import type { KpiTone, KpiVM } from "@/disciplines/overwatch/analytics/analytics.helpers";

import InfoDot from "./InfoDot";
import { moveTone } from "./DeltaText";

/** Colour only where the figure is a direction (DESIGN.md §2): climbers gain, droppers lose; the rest stay neutral. */
const VALUE_COLOR: Partial<Record<KpiTone, string>> = { up: moveTone(1), down: moveTone(-1) };

// Three across wherever the hero's right column is wide (stacked below `lg`, or from `xl`); two in the narrow `lg` aside.
// `items-end`: a label that wraps (a long word beside its explainer) must not push its figure off the row's line.
const GRID = "grid grid-cols-2 items-end gap-x-7 gap-y-5 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3";

interface KpiStatsProps {
  kpis: KpiVM[];
  onExplain: (term: GlossaryTerm) => void;
}

/** The board's six headline figures as the hero's `HeroStat`s, each with its glossary explainer. */
export default function KpiStats({ kpis, onExplain }: Readonly<KpiStatsProps>) {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <div className={GRID}>
      {kpis.map((kpi) => (
        <HeroStat
          key={kpi.id}
          label={
            <span className="inline-flex items-center gap-0.5">
              {t(`analytics.community.kpi.${kpi.id}`)}
              <InfoDot term={kpi.glossaryTerm} onExplain={onExplain} />
            </span>
          }
          value={
            <span style={{ color: VALUE_COLOR[kpi.tone] }}>
              {kpi.id === "avgConfidence"
                ? format.number(kpi.value, { style: "percent", maximumFractionDigits: 0 })
                : format.number(kpi.value)}
            </span>
          }
          sub={t(`analytics.community.kpi.${kpi.id}Foot`)}
        />
      ))}
    </div>
  );
}

/** The six figures' footprint while the result loads, so the hero does not grow when they land. */
export function KpiStatsSkeleton() {
  return (
    <div className={GRID} aria-hidden>
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="flex flex-col gap-1.5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-12" />
          <Skeleton className="h-3 w-24" />
        </div>
      ))}
    </div>
  );
}
