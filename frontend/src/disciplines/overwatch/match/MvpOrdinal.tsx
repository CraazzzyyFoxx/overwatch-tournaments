"use client";

import type { ReactElement } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { SlotProps } from "@/disciplines/types";
import { observedScore } from "@/lib/encounter/detail";
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

/**
 * The MVP breakdown card a placement chip (`children`) opens on hover: new impact rank, legacy rank,
 * overperformance, read from one member's facts. `header` titles the card; `badge` marks the
 * overperformance badge as earned. Must be rendered inside a `TooltipProvider`.
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
  const over = formatOverperformance(facts?.overperformance_score);

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
          <RankLine label={t("users.matches.mvp.newRank")} rank={facts?.impact_rank} />
          <RankLine label={t("users.matches.mvp.oldRank")} rank={facts?.performance} />
          {over ? (
            <div className="flex items-center justify-between gap-3">
              <span className={badge ? "font-semibold text-foreground" : "text-muted-foreground"}>
                {t("users.matches.overperformanceBadge")}
              </span>
              <span
                className="aqt-tnum font-semibold"
                style={{ color: over.raised ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
              >
                {over.text}
              </span>
            </div>
          ) : null}
        </div>
      </TooltipContent>
    </Tooltip>
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
      // Top of the match by overperformance and past the threshold: the "above expectations" row is the badge.
      badge={overperformanceBadge(match)}
      header={{ title: match.map.name, aside: scores.join(" – ") }}
    >
      <Badge
        tone={placement === 1 ? undefined : "neutral"}
        hue={placement === 1 ? "var(--aqt-medal-gold)" : undefined}
        className="aqt-tnum min-w-9.5 cursor-default justify-center font-semibold"
      >
        {ordinal(placement)}
      </Badge>
    </MvpTooltip>
  );
}
