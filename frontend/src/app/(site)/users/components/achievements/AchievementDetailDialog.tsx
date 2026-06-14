"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import type { AchievementRarity, AchievementMatchLink } from "@/types/achievement.types";
import { cn } from "@/lib/utils";
import { classifyRarity, type Rarity } from "./rarity";

const formatMatchDate = (time: number): string => {
  if (!time) return "";
  const ms = time > 1e12 ? time : time * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
};

const MatchRow = ({ match }: { match: AchievementMatchLink }) => {
  const date = formatMatchDate(match.time);
  const home = match.home_team?.name ?? "—";
  const away = match.away_team?.name ?? "—";
  return (
    <Link
      href={`/encounters/${match.encounter_id}`}
      className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-2 text-[13.5px] transition-colors hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)]"
    >
      <span className="truncate">
        {home} <span className="aqt-mono opacity-80">{match.score.home}–{match.score.away}</span> {away}
      </span>
      {date ? <span className="aqt-mono shrink-0 text-[12px] text-[color:var(--aqt-fg-muted)]">{date}</span> : null}
    </Link>
  );
};

interface Props {
  achievement: AchievementRarity | null;
  onClose: () => void;
}

/** Detail modal for a single achievement: shows where/when the player earned it
 *  (tournaments + matches with dates), or a locked state if not yet earned. */
export const AchievementDetailDialog = ({ achievement, onClose }: Props) => {
  const ach = achievement;
  const rarity: Rarity | null = ach ? classifyRarity(ach.rarity * 100) : null;
  const locked = ach ? ach.count === 0 : false;
  const imgSrc = ach ? (ach.image_url ?? `/achievements/${ach.slug}.webp`) : null;
  const description = ach ? ach.description_ru || ach.description_en || "" : "";

  return (
    <Dialog
      open={!!ach}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-lg border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] p-0">
        <div className="aqt-player flex max-h-[80vh] flex-col">
          {ach ? (
            <>
              <DialogHeader className="border-b border-[color:var(--aqt-border)] px-5 py-4 text-left">
                <div className="flex items-start gap-3">
                  <div className={cn("aqt-ic-circle relative", rarity)} style={{ width: 52, height: 52 }}>
                    {imgSrc ? (
                      <Image src={imgSrc} alt={ach.name} fill sizes="52px" className="object-cover" />
                    ) : null}
                  </div>
                  <div className="flex min-w-0 flex-col gap-1">
                    <DialogTitle className="text-[16px] text-[color:var(--aqt-fg)]">{ach.name}</DialogTitle>
                    <div className="flex items-center gap-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
                      {rarity ? <span className="capitalize">◆ {rarity}</span> : null}
                      <span className="aqt-mono">{(ach.rarity * 100).toFixed(2)}%</span>
                      {ach.count > 0 ? <span className="aqt-mono">· earned ×{ach.count}</span> : null}
                    </div>
                  </div>
                </div>
              </DialogHeader>

              <div className="flex flex-col gap-4 overflow-y-auto px-5 py-4">
                <DialogDescription className="text-[14px] leading-snug text-[color:var(--aqt-fg-dim)]">
                  {description || "Achievement details."}
                </DialogDescription>

                {locked ? (
                  <div className="rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-3 text-center text-[13.5px] text-[color:var(--aqt-fg-muted)]">
                    You haven&apos;t earned this achievement yet.
                  </div>
                ) : (
                  <>
                    {ach.tournaments.length > 0 ? (
                      <section className="flex flex-col gap-1.5">
                        <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                          Earned in
                        </h3>
                        <div className="flex flex-wrap gap-1.5">
                          {ach.tournaments.map((t) => (
                            <span key={t.id} className="aqt-stage-pill" title={t.name}>
                              {t.number != null ? `#${t.number} · ` : ""}
                              {t.name}
                            </span>
                          ))}
                        </div>
                      </section>
                    ) : null}

                    {ach.matches.length > 0 ? (
                      <section className="flex flex-col gap-1.5">
                        <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                          Matches
                        </h3>
                        <div className="flex flex-col gap-1">
                          {ach.matches.map((m) => (
                            <MatchRow key={m.id} match={m} />
                          ))}
                        </div>
                      </section>
                    ) : null}

                    {ach.tournaments.length === 0 && ach.matches.length === 0 ? (
                      <div className="text-center text-[13.5px] text-[color:var(--aqt-fg-muted)]">
                        Earned {ach.count}× — no tournament or match details recorded.
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            </>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default AchievementDetailDialog;
