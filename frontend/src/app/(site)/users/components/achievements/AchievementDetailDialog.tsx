"use client";

import { AchievementArt } from "@/components/achievements/AchievementArt";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useLocale, useTranslations } from "next-intl";
import { formatSeriesClock, observedScore } from "@/lib/encounter/detail";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Eyebrow } from "@/components/ui/eyebrow";
import type { AchievementRarity, AchievementMatchLink } from "@/types/achievement.types";
import { cn } from "@/lib/utils";
import { classifyRarity, localizedText, rarityVarClass, type Rarity } from "@/lib/achievements/rarity";

const MatchRow = ({ match }: { match: AchievementMatchLink }) => {
  const t = useTranslations();
  // The link carries the map's length in seconds, never a date.
  const duration = formatSeriesClock(match.duration_s, {
    h: t("common.duration.h"),
    m: t("common.duration.m"),
    s: t("common.duration.s")
  });
  const scores = match.participants.map((participant) => observedScore(participant) ?? "?");
  const [home, away] = match.participants;
  return (
    <HoverPrefetchLink
      href={`/matches/${match.id}`}
      className="flex items-center justify-between gap-2 border-b border-[color:var(--aqt-border)] py-2 text-caption transition-colors last:border-b-0 hover:text-[color:var(--aqt-teal)]"
    >
      <span className="truncate">
        {match.participants.length === 2 ? (
          <>
            {home.name} <span className="aqt-tnum opacity-80">{scores.join(":")}</span> {away.name}
          </>
        ) : (
          <>
            {match.participants.map((participant) => participant.name).join(" · ")}{" "}
            <span className="aqt-tnum opacity-80">{scores.join(":")}</span>
          </>
        )}
      </span>
      {duration ? (
        <span className="aqt-tnum shrink-0 text-label text-[color:var(--aqt-fg-muted)]">{duration}</span>
      ) : null}
    </HoverPrefetchLink>
  );
};

interface Props {
  achievement: AchievementRarity | null;
  onClose: () => void;
}

/** Detail modal for a single achievement: where the player earned it (each tournament and match linking to its
 *  own page; a match shows its participants, score line and length), or a locked state if not yet earned. */
export const AchievementDetailDialog = ({ achievement, onClose }: Props) => {
  const tr = useTranslations();
  const locale = useLocale();
  const ach = achievement;
  const rarity: Rarity | null = ach ? classifyRarity(ach.rarity * 100) : null;
  const locked = ach ? ach.count === 0 : false;
  const description = ach ? localizedText(locale, ach.description_ru, ach.description_en) : "";

  return (
    <Dialog
      open={!!ach}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent variant="panel">
        <div className="aqt-player flex max-h-[80vh] flex-col">
          {ach ? (
            <>
              <DialogHeader variant="panel">
                <div className="flex items-start gap-3">
                  <AchievementArt achievement={ach} sizes="52px" className="size-[52px] shrink-0 rounded-xl" />
                  <div className="flex min-w-0 flex-col gap-1">
                    <DialogTitle>{ach.name}</DialogTitle>
                    <div className="flex items-center gap-2 text-label text-[color:var(--aqt-fg-muted)]">
                      {rarity ? (
                        <span className={cn(rarityVarClass(rarity), "text-[hsl(var(--rar))]")}>
                          {tr(`achievements.rarityName.${rarity}`)}
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
                <DialogDescription>
                  {description || tr("users.achievements.detail.fallbackDescription")}
                </DialogDescription>

                {locked ? (
                  <div className="text-center text-caption text-[color:var(--aqt-fg-muted)]">
                    {tr("users.achievements.detail.locked")}
                  </div>
                ) : (
                  <>
                    {ach.tournaments.length > 0 ? (
                      <section className="flex flex-col gap-1.5">
                        <Eyebrow as="h3">{tr("users.achievements.detail.earnedIn")}</Eyebrow>
                        {/* Tournament names are user content: a text line, not uppercase chips (DESIGN §4). */}
                        <p className="text-caption leading-relaxed text-[color:var(--aqt-fg-muted)]">
                          {ach.tournaments.map((t, i) => (
                            <span key={t.id}>
                              {i > 0 ? <span aria-hidden className="text-[color:var(--aqt-fg-dim)]"> · </span> : null}
                              <HoverPrefetchLink
                                href={`/tournaments/${t.id}`}
                                className="text-[color:var(--aqt-fg)] transition-colors hover:text-[color:var(--aqt-teal)]"
                              >
                                {t.name}
                              </HoverPrefetchLink>
                            </span>
                          ))}
                        </p>
                      </section>
                    ) : null}

                    {ach.matches.length > 0 ? (
                      <section className="flex flex-col gap-1.5">
                        <Eyebrow as="h3">{tr("common.matches")}</Eyebrow>
                        <div className="flex flex-col">
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
