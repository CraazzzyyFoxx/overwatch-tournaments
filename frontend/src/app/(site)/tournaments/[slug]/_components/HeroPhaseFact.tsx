"use client";

import { useTranslations } from "next-intl";

import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { getTournamentStatusMeta, displayStatus } from "@/lib/tournament/status";
import { pickCurrentStage } from "@/lib/tournament/stages";
import type { Tournament } from "@/types/tournament.types";

import { useTournamentPlayedCount } from "../_hooks/useTournamentPlayedCount";
import { useNextPhase } from "./NextPhaseChip";

/**
 * The hero's one big fact about this moment of the tournament, under its name:
 * before the start, the next boundary ("Start · in 12 hours", with the date
 * under it); while it is played, the stage being played and how much of it is
 * done. A finished tournament gets none — the result right under the tabs is
 * its answer — and keeps only the counts line.
 *
 * `counts` is "14 teams · 70 players", passed in only once the field is set
 * (`hasTeamLineup`): before that the overview's registration block owns the
 * numbers, and the hero repeating them would say one fact twice.
 */
export function HeroPhaseFact({
  tournament,
  counts
}: Readonly<{ tournament: Tournament; counts: string | null }>) {
  const t = useTranslations();
  const isLive = getTournamentStatusMeta(displayStatus(tournament)).variant === "live";
  const next = useNextPhase(tournament);
  const played = useTournamentPlayedCount(tournament, isLive);
  const stage = isLive ? pickCurrentStage(tournament.stages, tournament.status) : null;

  const fact = stage
    ? {
        label: t("tournamentDetail.phaseFact.stage"),
        value: stage.name,
        detail: played ? t("tournamentDetail.phaseFact.played", played) : null
      }
    : next
      ? {
          label: next.label,
          value: next.relative,
          detail: <time dateTime={next.at}>{next.stamp}</time>
        }
      : null;

  if (fact === null && counts === null) return null;

  return (
    <div className="flex min-w-0 flex-col gap-1">
      {fact ? (
        <>
          <Eyebrow>{fact.label}</Eyebrow>
          <span className="font-onest text-headline font-bold text-[color:var(--aqt-fg)]">
            {fact.value}
          </span>
        </>
      ) : null}
      {fact?.detail || counts ? (
        <p className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]">
          {fact?.detail}
          {/* Two lines below `sm`, one above: on a phone the cover sits behind
              the right half of the hero, and a short line stays clear of it. */}
          {fact?.detail && counts ? (
            <span className="hidden text-[color:var(--aqt-fg-dim)] sm:inline"> · </span>
          ) : null}
          {counts ? <span className="block sm:inline">{counts}</span> : null}
        </p>
      ) : null}
    </div>
  );
}
