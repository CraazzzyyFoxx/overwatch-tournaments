"use client";

import { Pause, Radio, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroCoord, HeroStamp, HeroStat, PageHero } from "@/components/site/PageHero";
import { cn } from "@/lib/utils";
import type { DraftBoard } from "@/types/draft.types";
import type { Tournament } from "@/types/tournament.types";

import { DraftClock } from "./DraftClock";

interface DraftPageHeroProps {
  tournament: Tournament;
  board: DraftBoard;
  mode: "captain" | "spectator";
}

export function DraftPageHero({ tournament, board, mode }: DraftPageHeroProps) {
  const t = useTranslations("draftRedesign");
  const session = board.session;
  const current = board.current_pick;
  const team = current
    ? board.teams.find((candidate) => candidate.id === current.draft_team_id) ?? null
    : null;
  const completed = board.picks.filter((pick) =>
    ["completed", "autopicked", "skipped"].includes(pick.status)
  ).length;
  const stateIcon = session.status === "paused" ? Pause : session.blocked_reason ? ShieldAlert : Radio;
  const StateIcon = stateIcon;

  return (
    <PageHero
      eyebrow={
        <>
          <HeroCoord>{t("coordinate", { tournament: tournament.id, session: session.id })}</HeroCoord>
          <HeroCoord>{t(`mode.${mode}`)}</HeroCoord>
        </>
      }
      title={<>{tournament.name} <em>{t("draftAccent")}</em></>}
      lede={mode === "captain" ? t("captainLede") : t("spectatorLede")}
      meta={
        <span className="inline-flex min-h-8 items-center gap-2 rounded-lg border border-[color:var(--aqt-border-2)] px-3 text-sm">
          <StateIcon
            className={cn(
              "h-4 w-4",
              session.status === "live" ? "text-[color:var(--aqt-live)]" : "text-[color:var(--aqt-warm)]"
            )}
          />
          {t(`status.${session.status}`)}
        </span>
      }
      stamp={
        <>
          <HeroStamp label={t("format")} value={session.format} />
          <HeroStamp label={t("rosterSize")} value={session.team_size} />
          <HeroStamp label={t("teams")} value={board.teams.length} />
        </>
      }
      aside={
        <div className="grid grid-cols-3 gap-5 border-t border-[color:var(--aqt-border)] pt-5 lg:border-t-0 lg:pt-0">
          <HeroStat label={t("progress")} value={`${completed}/${board.picks.length}`} />
          <HeroStat label={t("onClock")} value={team?.name ?? "—"} className="min-w-0 [&>span:nth-child(2)]:truncate [&>span:nth-child(2)]:text-xl" />
          <HeroStat
            label={t("timeLeft")}
            value={
              <DraftClock
                expiresAt={current?.clock_expires_at ?? null}
                paused={session.status === "paused"}
                compact
              />
            }
          />
        </div>
      }
    />
  );
}
