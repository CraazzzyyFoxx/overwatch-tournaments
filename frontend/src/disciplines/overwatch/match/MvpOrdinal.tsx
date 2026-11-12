"use client";

import type { HTMLAttributes, ReactElement } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import type { SlotProps } from "@/disciplines/types";
import { observedScore } from "@/lib/encounter/detail";
import { STAT_META } from "./stats";
import { formatOverperformance, ordinal, overperformanceBadge, resolveMvpPlacement } from "./mvp";

/** Gold only for 1st, every other placement neutral (design-book MVP rule). */
const RankLine = ({ label, rank }: { label: string; rank: number | null | undefined }) => (
  <div className="flex items-center justify-between gap-3">
    <span className="text-muted-foreground">{label}</span>
    <span
      className="aqt-tnum font-semibold"
      style={{ color: rank === 1 ? "var(--aqt-gold)" : "var(--aqt-fg-faint)" }}
    >
      {rank != null ? ordinal(rank) : "—"}
    </span>
  </div>
);

const CONTRIB_PREFIX = "contrib_";
const TOP_POSITIVE = 3;
const TOP_NEGATIVE = 2;
/** Contributions are small (a map's impact spans about ±1): two decimals, and a row that would read 0.00 is noise. */
const CONTRIB_DIGITS = 2;
const CONTRIB_FLOOR = 0.005;

/** A signed value row (positive / negative colour, optional bold label); nothing for an absent score. */
const SignedLine = ({
  label,
  score,
  strong = false,
  digits = 1
}: {
  label: string;
  score: number | null | undefined;
  strong?: boolean;
  digits?: number;
}) => {
  const value = formatOverperformance(score, digits);
  return value ? (
    <div className="flex items-center justify-between gap-3">
      <span className={strong ? "font-semibold text-foreground" : "text-muted-foreground"}>{label}</span>
      <span
        className="aqt-tnum font-semibold"
        style={{ color: value.raised ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
      >
        {value.text}
      </span>
    </div>
  ) : null;
};

/** Strongest per-feature impact contributions of a map's facts: the top positive ones, then the top negative ones. */
export const topContributions = (facts: Readonly<Record<string, number>> | undefined) => {
  const entries = Object.entries(facts ?? {}).flatMap(([code, value]) => {
    const meta = code.startsWith(CONTRIB_PREFIX) ? STAT_META[code.slice(CONTRIB_PREFIX.length)] : undefined;
    return meta && Number.isFinite(value) && Math.abs(value) >= CONTRIB_FLOOR ? [{ labelKey: meta.labelKey, value }] : [];
  });
  return [
    ...entries.filter((e) => e.value > 0).sort((a, b) => b.value - a.value).slice(0, TOP_POSITIVE),
    ...entries.filter((e) => e.value < 0).sort((a, b) => a.value - b.value).slice(0, TOP_NEGATIVE)
  ];
};

/**
 * The MVP breakdown card a placement chip (`children`) opens on hover: the place, the strongest per-stat
 * contributions (map-level facts only) and the overperformance, read from one member's facts. `header` titles the
 * card; `badge` marks the overperformance badge as earned. Must be rendered inside a `TooltipProvider`.
 */
export function MvpTooltip({
  facts,
  badge = false,
  header,
  children
}: Readonly<{
  facts: Readonly<Record<string, number>> | undefined;
  badge?: boolean;
  header?: { title: string; aside: string };
  children: ReactElement;
}>) {
  const t = useTranslations();
  const place = resolveMvpPlacement(facts);
  const contributions = topContributions(facts);

  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent
        align="start"
        className="w-60 overflow-hidden p-0"
      >
        {header ? (
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <span className="truncate text-caption font-semibold text-foreground">{header.title}</span>
            <span className="aqt-tnum shrink-0 text-label text-muted-foreground">{header.aside}</span>
          </div>
        ) : null}
        <div className="flex flex-col gap-2 px-3 py-2.5 text-caption">
          <RankLine label={t("users.matches.mvp.place")} rank={place} />
          {contributions.map(({ labelKey, value }) => (
            <SignedLine
              key={labelKey}
              label={t(labelKey as Parameters<typeof t>[0])}
              score={value}
              digits={CONTRIB_DIGITS}
            />
          ))}
          <SignedLine
            label={t("users.matches.overperformanceBadge")}
            score={facts?.overperformance_score}
            strong={badge}
          />
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * The MVP placement chip every list draws (profile rows, the match scoreboard): gold for 1st only, every other
 * placement neutral (DESIGN §6). `size="sm"` for a dense table. Other props reach the chip, so a tooltip trigger
 * can wrap it directly.
 */
export function MvpPlacementBadge({
  placement,
  size,
  className,
  ...props
}: Readonly<{ placement: number; size?: "default" | "sm" } & HTMLAttributes<HTMLSpanElement>>) {
  return (
    <Badge
      tone={placement === 1 ? undefined : "neutral"}
      hue={placement === 1 ? "var(--aqt-medal-gold)" : undefined}
      size={size}
      className={cn(
        "aqt-tnum cursor-default justify-center font-semibold",
        size === "sm" ? "h-5.5 min-w-8" : "min-w-9.5",
        className
      )}
      {...props}
    >
      {ordinal(placement)}
    </Badge>
  );
}

/**
 * Profile-local MVP placement: a square chip that opens the `MvpTooltip` breakdown, headed by the map
 * and its score. Gold for 1st only, every other placement neutral (DESIGN §6). Reads the viewer's
 * whole-match facts. Must be rendered inside a `TooltipProvider`.
 */
export default function MvpOrdinal({ match }: Readonly<SlotProps["matchRowBadge"]>) {
  const facts = match.viewer?.facts;
  const placement = resolveMvpPlacement(facts);
  if (placement == null) return null;

  const scores = match.participants.map((participant) => observedScore(participant) ?? "—");

  return (
    <MvpTooltip
      facts={facts}
      // The stored `overperformance_badge` fact: the "above expectations" row is the badge.
      badge={overperformanceBadge(match)}
      header={{ title: match.map.name, aside: scores.join(" – ") }}
    >
      <MvpPlacementBadge placement={placement} />
    </MvpTooltip>
  );
}
