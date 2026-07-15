"use client";

import { Bookmark, Flag, HelpCircle, X } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import type { DraftPlayer } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

interface CaptainShortlistProps {
  players: DraftPlayer[];
  onSelect: (player: DraftPlayer) => void;
  onRemove: (playerId: number) => void;
  divisionGrid: DivisionGrid;
  variant?: "panel" | "chips";
}

export function CaptainShortlist({ players, onSelect, onRemove, divisionGrid, variant = "panel" }: CaptainShortlistProps) {
  const t = useTranslations("draftRedesign");

  if (variant === "chips") {
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
        {players.length > 0 &&
          players.map((player) => {
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

  return (
    <section className="border-t border-[color:var(--aqt-border)] pt-5" aria-labelledby="shortlist-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="shortlist-heading" className="flex items-center gap-2 text-sm font-medium text-[color:var(--aqt-fg-muted)]"><Bookmark className="h-4 w-4 text-[color:var(--aqt-teal)]" />{t("shortlist")}</h2>
        <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">{players.length}</span>
      </div>
      {players.length === 0 ? (
        <p className="mt-3 text-sm text-[color:var(--aqt-fg-muted)]">{t("shortlistEmpty")}</p>
      ) : (
        <div className="mt-2 divide-y divide-[color:var(--aqt-border)]">
          {players.map((player) => (
            <div key={player.id} className="flex min-h-11 items-center gap-2 py-1">
              <button type="button" className="min-h-11 min-w-0 flex-1 truncate rounded-md text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]" onClick={() => onSelect(player)}>{player.battle_tag ?? `#${player.id}`}</button>
              <Button size="icon" variant="ghost" className="h-11 w-11" onClick={() => onRemove(player.id)} aria-label={t("removeShortlist")}><X className="h-4 w-4" /></Button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

