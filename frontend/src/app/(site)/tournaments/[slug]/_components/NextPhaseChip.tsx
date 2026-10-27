"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { useMinuteClock } from "@/hooks/useMinuteClock";
import { Button } from "@/components/ui/button";
import { eyebrowClass } from "@/components/ui/eyebrow";
import type { Tournament } from "@/types/tournament.types";

import { nextPhaseBoundary } from "../_views/tournamentSchedule.model";

type PhaseInput = Pick<
  Tournament,
  "status" | "team_formation" | "phase_schedule" | "auto_transitions_enabled"
>;

export type NextPhase = {
  /** "Registration closes", "Check-in starts", "Start": what happens. */
  label: string;
  /** "in 12 hours": when, relative to the viewer's clock. */
  relative: string;
  /** "Sat, Oct 24, 16:00": when, on the viewer's calendar. */
  stamp: string;
  /** The boundary itself, ISO-8601, for `<time dateTime>`. */
  at: string;
};

const STAMP = {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit"
} as const;

/**
 * The one boundary ahead of the tournament, worded once for both places that
 * quote it: the overview hero and the collapsed rail's pill. Null until
 * hydration (the minute clock), and null when nothing lies ahead, so a finished
 * tournament carries no stale promise.
 */
export function useNextPhase(tournament: PhaseInput): NextPhase | null {
  const t = useTranslations();
  const format = useFormatter();
  const now = useMinuteClock();

  if (now === null) return null;
  const next = nextPhaseBoundary({ tournament, now });
  if (!next) return null;

  const at = new Date(next.at);
  const phase = t(`common.statusBadge.${next.status}`);
  // The live phase is the tournament itself: its start is "the start", its
  // close the end — "Live starts" would read as a status, not as an event.
  const label =
    next.status === "live"
      ? t(next.kind === "close" ? "tournamentDetail.phaseFact.ends" : "tournamentDetail.phaseFact.kickoff")
      : t(next.kind === "close" ? "tournamentDetail.phaseFact.closes" : "tournamentDetail.phaseFact.starts", {
          phase
        });

  return {
    label,
    relative: format.relativeTime(at, now),
    stamp: format.dateTime(at, STAMP),
    at: next.at
  };
}

/**
 * The next boundary as a pill in the collapsed rail, beside the title and the
 * register button — the widest thing in a row that has none to spare. It keeps
 * the answer ("in 13 hours") and the event; the absolute stamp rides in
 * `title`, since the hero and the timeline it links to both print it.
 */
export function NextPhaseChip({
  tournament,
  href,
  className
}: Readonly<{
  tournament: PhaseInput;
  /** Where the chip leads — the overview's phase timeline. */
  href: string;
  className?: string;
}>) {
  const next = useNextPhase(tournament);
  if (!next) return null;

  return (
    <Button asChild variant="outline" size="xs" className={className}>
      <Link href={href} title={`${next.label} · ${next.stamp}`}>
        <span className={eyebrowClass()}>{next.label}</span>
        <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">{next.relative}</span>
      </Link>
    </Button>
  );
}
