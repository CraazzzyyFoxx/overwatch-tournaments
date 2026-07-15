"use client";

import { Bookmark, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { DraftPlayer } from "@/types/draft.types";

interface CaptainShortlistProps {
  players: DraftPlayer[];
  onSelect: (player: DraftPlayer) => void;
  onRemove: (playerId: number) => void;
}

export function CaptainShortlist({ players, onSelect, onRemove }: CaptainShortlistProps) {
  const t = useTranslations("draftRedesign");
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

