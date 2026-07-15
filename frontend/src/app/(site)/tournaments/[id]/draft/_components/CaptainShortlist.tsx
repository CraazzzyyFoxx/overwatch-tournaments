"use client";

import { Flag, HelpCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import type { DraftPlayer } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

interface CaptainShortlistProps {
  players: DraftPlayer[];
  onSelect: (player: DraftPlayer) => void;
  onRemove: (playerId: number) => void;
  divisionGrid: DivisionGrid;
}

export function CaptainShortlist({ players, onSelect, onRemove, divisionGrid }: CaptainShortlistProps) {
  const t = useTranslations("draftRedesign");
  if (players.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("shortlist")}>
      <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.13em] text-[color:var(--aqt-fg-muted)]">
        <Flag className="h-3 w-3 text-[color:var(--aqt-teal)]" aria-hidden />
        {t("shortlist")}
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="grid h-4 w-4 place-items-center rounded-full text-[color:var(--aqt-fg-faint)] outline-none transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                aria-label={t("howItWorks")}
              >
                <HelpCircle className="h-3.5 w-3.5" aria-hidden />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[16rem] font-sans text-xs normal-case tracking-normal">
              {t("shortlistEmpty")}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </span>
      {players.map((player) => {
        const division = player.division_number ?? resolveDivisionFromRank(divisionGrid, player.rank_value);
        return (
          <div key={player.id} className="inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] py-1 pl-1.5 pr-1 text-xs font-semibold transition-colors hover:border-[color:var(--aqt-teal)]">
            <button type="button" className="flex min-w-0 items-center gap-1.5 rounded outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]" onClick={() => onSelect(player)}>
              {division != null && (
                <PlayerDivisionIcon division={division} tournamentGrid={divisionGrid} width={20} height={20} className="h-5 w-5 shrink-0 object-contain" />
              )}
              <span className="min-w-0 truncate">{player.battle_tag ?? `#${player.id}`}</span>
            </button>
            <button type="button" className="grid h-5 w-5 shrink-0 place-items-center rounded text-[color:var(--aqt-fg-muted)] outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]" onClick={() => onRemove(player.id)} aria-label={t("removeShortlist")}>×</button>
          </div>
        );
      })}
    </div>
  );
}
