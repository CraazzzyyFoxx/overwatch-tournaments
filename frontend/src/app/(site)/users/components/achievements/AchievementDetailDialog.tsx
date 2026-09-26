"use client";

import Image from "next/image";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useLocale, useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import type { AchievementRarity, AchievementMatchLink } from "@/types/achievement.types";
import { cn } from "@/lib/utils";
import { classifyRarity, localizedText, type Rarity } from "./rarity";

const MatchRow = ({ match }: { match: AchievementMatchLink }) => {
  const format = useFormatter();
  // Older rows store seconds, newer ones milliseconds.
  const ms = match.time ? (match.time > 1e12 ? match.time : match.time * 1000) : null;
  const at = ms === null ? null : new Date(ms);
  const date =
    at && !Number.isNaN(at.getTime())
      ? format.dateTime(at, { year: "numeric", month: "short", day: "numeric" })
      : "";
  const home = match.home_team?.name ?? "—";
  const away = match.away_team?.name ?? "—";
  return (
    <HoverPrefetchLink
      href={`/encounters/${match.encounter_id}`}
      className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-2 text-caption transition-colors hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)]"
    >
      <span className="truncate">
        {home} <span className="aqt-tnum opacity-80">{match.score.home}–{match.score.away}</span> {away}
      </span>
      {date ? <span className="aqt-tnum shrink-0 text-label text-[color:var(--aqt-fg-muted)]">{date}</span> : null}
    </HoverPrefetchLink>
  );
};

interface Props {
  achievement: AchievementRarity | null;
  onClose: () => void;
}

/** Detail modal for a single achievement: shows where/when the player earned it
 *  (tournaments + matches with dates), or a locked state if not yet earned. */
export const AchievementDetailDialog = ({ achievement, onClose }: Props) => {
  const tr = useTranslations();
  const locale = useLocale();
  const ach = achievement;
  const rarity: Rarity | null = ach ? classifyRarity(ach.rarity * 100) : null;
  const locked = ach ? ach.count === 0 : false;
  const imgSrc = ach ? (ach.image_url ?? `/achievements/${ach.slug}.webp`) : null;
  const description = ach ? localizedText(locale, ach.description_ru, ach.description_en) : "";

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
                    <DialogTitle className="text-base text-[color:var(--aqt-fg)]">{ach.name}</DialogTitle>
                    <div className="flex items-center gap-2 text-label text-[color:var(--aqt-fg-muted)]">
                      {rarity ? (
                        <span className="capitalize">
                          <span aria-hidden>◆</span> {rarity}
                        </span>
                      ) : null}
                      <span className="aqt-tnum">{(ach.rarity * 100).toFixed(2)}%</span>
                      {ach.count > 0 ? (
                        <span className="aqt-tnum">
                          {tr("users.achievements.detail.earnedCount", { count: String(ach.count) })}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
              </DialogHeader>

              <div className="flex flex-col gap-4 overflow-y-auto px-5 py-4">
                <DialogDescription className="text-body leading-snug text-[color:var(--aqt-fg-dim)]">
                  {description || tr("users.achievements.detail.fallbackDescription")}
                </DialogDescription>

                {locked ? (
                  <div className="rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-3 text-center text-caption text-[color:var(--aqt-fg-muted)]">
                    {tr("users.achievements.detail.locked")}
                  </div>
                ) : (
                  <>
                    {ach.tournaments.length > 0 ? (
                      <section className="flex flex-col gap-1.5">
                        <h3 className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                          {tr("users.achievements.detail.earnedIn")}
                        </h3>
                        <div className="flex flex-wrap gap-1.5">
                          {ach.tournaments.map((t) => (
                            <span key={t.id} className="aqt-stage-pill" title={t.name}>
                              {t.name}
                            </span>
                          ))}
                        </div>
                      </section>
                    ) : null}

                    {ach.matches.length > 0 ? (
                      <section className="flex flex-col gap-1.5">
                        <h3 className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                          {tr("common.matches")}
                        </h3>
                        <div className="flex flex-col gap-1">
                          {ach.matches.map((m) => (
                            <MatchRow key={m.id} match={m} />
                          ))}
                        </div>
                      </section>
                    ) : null}

                    {ach.tournaments.length === 0 && ach.matches.length === 0 ? (
                      <div className="text-center text-caption text-[color:var(--aqt-fg-muted)]">
                        {tr("users.achievements.detail.earnedNoDetails", { count: String(ach.count) })}
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
