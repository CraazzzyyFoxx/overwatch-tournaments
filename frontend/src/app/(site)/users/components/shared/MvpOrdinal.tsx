"use client";

import { useTranslations } from "next-intl";
import { formatOverperformance, ordinal, resolveMvpPlacement } from "@/components/match/cells";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { MatchWithUserStats } from "@/types/user.types";

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
 * Profile-local MVP placement: a plain ordinal (no chip) that opens the same
 * breakdown card as elsewhere — new impact rank, legacy rank, overperformance.
 * Must be rendered inside a `TooltipProvider`.
 */
export const MvpOrdinal = ({ match }: { match: MatchWithUserStats }) => {
  const t = useTranslations();
  const placement = resolveMvpPlacement(match);
  if (placement == null) return null;

  const over = formatOverperformance(match.overperformance_score);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="aqt-tnum cursor-default text-ui font-bold"
          style={{ color: placement === 1 ? "var(--aqt-gold)" : "var(--aqt-fg-faint)" }}
        >
          {ordinal(placement)}
        </span>
      </TooltipTrigger>
      <TooltipContent
        align="start"
        className="w-60 overflow-hidden border bg-popover p-0 text-popover-foreground shadow-md"
      >
        {match.map ? (
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <span className="truncate text-caption font-semibold text-foreground">{match.map.name}</span>
            <span className="aqt-tnum shrink-0 text-label text-muted-foreground">
              {match.score.home} – {match.score.away}
            </span>
          </div>
        ) : null}
        <div className="flex flex-col gap-2 px-3 py-2.5 text-caption">
          <RankLine label={t("users.matches.mvp.newRank")} rank={match.impact_rank} />
          <RankLine label={t("users.matches.mvp.oldRank")} rank={match.performance} />
          {over ? (
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{t("users.matches.overperformanceBadge")}</span>
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
};

export default MvpOrdinal;
