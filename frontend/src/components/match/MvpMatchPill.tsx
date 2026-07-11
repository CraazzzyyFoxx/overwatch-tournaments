"use client";

import React from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { MvpPill, formatOverperformance, mvpRank, ordinal, resolveMvpPlacement } from "@/components/match/cells";
import { cn } from "@/lib/utils";
import type { MatchWithUserStats } from "@/types/user.types";

/** One "<label> … <rank chip>" line in the card. Shows an em dash when the rank is absent. */
const RankRow = ({ label, rank }: { label: string; rank: number | null | undefined }) => (
  <div className="flex items-center justify-between gap-3">
    <span className="text-xs text-muted-foreground">{label}</span>
    {rank != null ? (
      <MvpPill rank={mvpRank(rank)} label={ordinal(rank)} />
    ) : (
      <span className="text-xs tabular-nums text-muted-foreground">—</span>
    )}
  </div>
);

/**
 * MVP-placement pill for a single map. The anchor shows the OFFICIAL placement
 * on the 1 (best) … 10 (worst) scale — the new impact rank when computed,
 * falling back to legacy performance. Hovering opens a card that compares the
 * old rank, the new rank, and how much better/worse than expected the player
 * performed (overperformance). Requires a <TooltipProvider> ancestor (the
 * profile match/encounter rows provide one). Renders nothing when the match
 * has no recorded placement.
 */
export const MvpMatchPill = ({ match }: { match: MatchWithUserStats }) => {
  const t = useTranslations();
  const placement = resolveMvpPlacement(match);
  if (placement == null) return null;

  const map = match.map;
  const over = formatOverperformance(match.overperformance_score);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-default">
          <MvpPill rank={mvpRank(placement)} label={ordinal(placement)} />
        </span>
      </TooltipTrigger>
      {/* Override the tooltip's default solid-primary surface with the popover card look. */}
      <TooltipContent
        align="start"
        className="w-64 overflow-hidden border bg-popover p-0 text-popover-foreground shadow-md"
      >
        {map ? (
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <span className="truncate text-[13px] font-semibold text-foreground">{map.name}</span>
            <span className="aqt-mono shrink-0 text-[12px] text-muted-foreground">
              {match.score.home} – {match.score.away}
            </span>
          </div>
        ) : null}
        <div className="flex flex-col gap-2 px-3 py-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("users.matches.mvp.title")}
          </p>
          <RankRow label={t("users.matches.mvp.newRank")} rank={match.impact_rank} />
          <RankRow label={t("users.matches.mvp.oldRank")} rank={match.performance} />
          {over ? (
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">{t("users.matches.overperformanceBadge")}</span>
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 text-xs font-medium tabular-nums",
                  over.raised ? "text-emerald-300" : "text-rose-300"
                )}
              >
                {over.raised ? (
                  <ArrowUp className="h-3 w-3" aria-hidden="true" />
                ) : (
                  <ArrowDown className="h-3 w-3" aria-hidden="true" />
                )}
                {over.text}
              </span>
            </div>
          ) : null}
        </div>
      </TooltipContent>
    </Tooltip>
  );
};

export default MvpMatchPill;
