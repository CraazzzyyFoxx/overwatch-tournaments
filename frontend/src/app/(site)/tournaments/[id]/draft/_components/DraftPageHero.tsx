"use client";

import { Pause, Radio, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroCoord, HeroStamp, HeroStat } from "@/components/site/PageHero";
import type { DraftBoard } from "@/types/draft.types";
import type { Tournament } from "@/types/tournament.types";

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
  const StateIcon = session.blocked_reason
    ? ShieldAlert
    : session.status === "paused"
      ? Pause
      : Radio;

  return (
    <section className="relative overflow-hidden border-y border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]/72">
      <span className="absolute inset-y-0 left-0 w-0.5 bg-[color:var(--aqt-teal)]" aria-hidden />
      <div className="grid gap-6 px-5 py-5 sm:px-7 sm:py-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.75fr)] lg:items-end lg:gap-10">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <HeroCoord>{t("coordinate", { tournament: tournament.id, session: session.id })}</HeroCoord>
            <HeroCoord>{t(`mode.${mode}`)}</HeroCoord>
            <span className="inline-flex min-h-8 items-center gap-2 rounded-lg border border-[color:var(--aqt-border-2)] px-3 text-xs font-medium">
              {session.status === "live" ? (
                <span
                  className="h-2 w-2 rounded-full bg-[color:var(--aqt-teal)] animate-pulse motion-reduce:animate-none"
                  aria-hidden
                />
              ) : (
                <StateIcon className="h-3.5 w-3.5 text-[color:var(--aqt-amber)]" />
              )}
              {t(`status.${session.status}`)}
            </span>
          </div>
          <h1 className="aqt-hero-title mt-3 max-w-4xl font-onest text-[clamp(1.85rem,4vw,3.15rem)] font-semibold leading-[1.02] tracking-[-0.02em]">
            {tournament.name} <em>{t("draftAccent")}</em>
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
            {mode === "captain" ? t("captainLede") : t("spectatorLede")}
          </p>
          <div className="mt-5 flex flex-wrap gap-x-7 gap-y-3">
            <HeroStamp label={t("format")} value={session.format} />
            <HeroStamp label={t("rosterSize")} value={session.team_size} />
            <HeroStamp label={t("teams")} value={board.teams.length} />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4 border-t border-[color:var(--aqt-border)] pt-5 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <HeroStat label={t("progress")} value={`${completed}/${board.picks.length}`} />
          <HeroStat
            label={t("onClock")}
            value={team?.name ?? "—"}
            className="min-w-0 [&>span:nth-child(2)]:truncate [&>span:nth-child(2)]:text-lg"
          />
          <HeroStat
            label={t("sequence")}
            value={
              <div className="flex flex-wrap gap-1" aria-label={t("progress")}>
                {board.picks.map((pick) => {
                  const done = ["completed", "autopicked", "skipped"].includes(pick.status);
                  const onClock = pick.status === "on_clock";
                  return (
                    <span
                      key={pick.id}
                      title={`#${pick.overall_no}`}
                      className={`h-1.5 w-1.5 rounded-full ${
                        done
                          ? "bg-[color:var(--aqt-support)]"
                          : onClock
                            ? "bg-[color:var(--aqt-teal)] animate-pulse motion-reduce:animate-none"
                            : "bg-[color:var(--aqt-fg-faint)]"
                      }`}
                    />
                  );
                })}
              </div>
            }
          />
        </div>
      </div>
    </section>
  );
}
