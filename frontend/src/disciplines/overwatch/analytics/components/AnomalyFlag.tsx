"use client";

import { Angry, Flag, TrendingDown, VenetianMask, Weight, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import { cn } from "@/lib/utils";
import type { AnalyticsAnomaly } from "@/types/analytics.types";

/** Reason codes the detector emits are localised; legacy raw metric expressions are dropped, never shown. */
const RAW_REASON = /[=<>]|\brule\b|\banomaly\b|\bmethod\b|changepoint|rolling|\bp\d/i;

/** The kinds the glossary names; any other kind reads as a generic watch flag. */
const FLAG_KINDS = ["smurf", "throw", "troll", "sandbag"] as const;
type FlagTerm = (typeof FLAG_KINDS)[number] | "watch";

/**
 * Each kind has its own glyph, so a row of flags reads at a glance without a
 * hue per kind: the colour stays the one warning tone (DESIGN.md §2).
 */
const KIND_ICON: Record<FlagTerm, LucideIcon> = {
  smurf: VenetianMask,
  throw: TrendingDown,
  troll: Angry,
  sandbag: Weight,
  watch: Flag
};

function flagTerm(kind: string): FlagTerm {
  return (FLAG_KINDS as readonly string[]).includes(kind) ? (kind as FlagTerm) : "watch";
}

/**
 * A flag's words: the kind's glossary label, its short name and one-line
 * meaning, and the localised reasons. An unknown kind reads as a generic watch
 * flag rather than the raw API value (DESIGN.md §11).
 */
export function useAnomalyCopy(kind: string, reasons: readonly string[] = []) {
  const t = useTranslations();
  const term = flagTerm(kind);
  const shownReasons = reasons
    .map((code): string | null => {
      const trimmed = (code ?? "").trim();
      if (!trimmed) return null;
      const key = `analytics.anomalyReason.${trimmed}`;
      // Runtime reason code: next-intl types keys as literals; the missing-key echo below still runs.
      const localised = t(key as Parameters<typeof t>[0]);
      if (localised !== key) return localised;
      return RAW_REASON.test(trimmed) ? null : trimmed;
    })
    .filter((reason): reason is string => reason !== null);
  return {
    label: t(`analytics.glossary.${term}.label`),
    short: t(`analytics.glossary.${term}.short`),
    plain: t(`analytics.glossary.${term}.plain`),
    reasons: shownReasons,
    reasonsLabel: t("analytics.glossary.reasonsLabel")
  };
}

interface AnomalyFlagProps {
  kind: string;
  reasons?: readonly string[];
  /** The kind in words beside its glyph: `short` in rows and cells, `full` where the flag is the heading. */
  label?: "short" | "full";
  /** How many flags of this kind the row carries, when it is more than one. */
  count?: number;
  className?: string;
}

/**
 * A watch flag: the kind's own glyph and name in the one warning tone, the
 * meaning and the reasons in the tooltip.
 */
export default function AnomalyFlag({ kind, reasons, label, count = 1, className }: Readonly<AnomalyFlagProps>) {
  const copy = useAnomalyCopy(kind, reasons);
  const Icon = KIND_ICON[flagTerm(kind)];
  const hint = (
    <>
      <span className="block">{copy.plain}</span>
      {copy.reasons.length > 0 ? (
        <span className="mt-1.5 block">
          <span className="block font-semibold">{copy.reasonsLabel}</span>
          {copy.reasons.map((reason, index) => (
            <span key={`${reason}-${index}`} className="block">
              {reason}
            </span>
          ))}
        </span>
      ) : null}
    </>
  );

  return (
    <IconTooltip
      label={count > 1 ? `${copy.label} ×${count}` : copy.label}
      hint={hint}
      className={cn("shrink-0 items-center gap-1 text-[color:var(--aqt-amber)]", className)}
    >
      <Icon aria-hidden className="size-3.5" />
      {label ? (
        <span className="whitespace-nowrap text-caption font-medium">
          {label === "full" ? copy.label : copy.short}
        </span>
      ) : null}
      {count > 1 ? <span className="aqt-tnum text-caption">×{count}</span> : null}
    </IconTooltip>
  );
}

/**
 * A team's flags by kind — one glyph and short name per kind, with its count —
 * so a summary row says *what* was flagged, not just how many.
 */
export function AnomalyKinds({ anomalies, className }: Readonly<{ anomalies: readonly AnalyticsAnomaly[]; className?: string }>) {
  const byKind = new Map<string, { count: number; reasons: string[] }>();
  for (const anomaly of anomalies) {
    const entry = byKind.get(anomaly.kind) ?? { count: 0, reasons: [] };
    entry.count += 1;
    entry.reasons.push(...anomaly.reasons);
    byKind.set(anomaly.kind, entry);
  }
  if (byKind.size === 0) return null;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-2.5 gap-y-1", className)}>
      {[...byKind].map(([kind, entry]) => (
        <AnomalyFlag key={kind} kind={kind} reasons={[...new Set(entry.reasons)]} count={entry.count} label="short" />
      ))}
    </span>
  );
}
