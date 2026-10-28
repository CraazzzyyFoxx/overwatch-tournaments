"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { Eyebrow } from "@/components/ui/eyebrow";
import { Separator } from "@/components/ui/separator";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

import { buildTournamentSchedule, type PhaseSegment } from "../_views/tournamentSchedule.model";

export type PhaseTimelineProps = {
  tournament: Pick<
    Tournament,
    "status" | "team_formation" | "phase_schedule" | "auto_transitions_enabled"
  >;
  /** Viewer clock override for deterministic tests; defaults to the minute clock. */
  now?: number;
  /** Anchor id, so the header chip can deep-link here. */
  id?: string;
  className?: string;
};

const STAMP = {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit"
} as const;

/**
 * The tournament's phase schedule as one vertical timeline: done / current /
 * upcoming, each step with its start or, for the next boundary, a countdown.
 *
 * Everything about WHICH phases appear and which is current comes from
 * `buildTournamentSchedule`; this component only draws the segments. Times are
 * the viewer's local time — the app formatter carries their zone.
 *
 * Teal marks exactly one thing: the phase happening now. A current phase whose
 * window has closed (registration over, check-in not yet open) is drawn in the
 * neutral scale with a "closed" tag — the countdown then sits on the next phase.
 */
export function PhaseTimeline({
  tournament,
  now: nowOverride,
  id,
  className
}: Readonly<PhaseTimelineProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const clock = useMinuteClock();
  const now = nowOverride ?? clock;

  // Server render and hydration render share this branch, so they cannot
  // disagree about an instant neither of them has.
  if (now === null) return null;

  const { segments } = buildTournamentSchedule({ tournament, now });
  if (segments.length === 0) return null;

  const stamp = (iso: string | null) => {
    if (iso === null) return null;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    return format.dateTime(date, STAMP);
  };
  // A current phase nobody scheduled has no time to print: "now" is its time.
  const nowText = <span className="text-[color:var(--aqt-teal)]">{t("common.now")}</span>;

  const countdown = (segment: PhaseSegment) => {
    if (segment.countdownMs === null || segment.countdownTo === null) return null;
    const relative = format.relativeTime(new Date(now + segment.countdownMs), now);
    return segment.countdownTo === "close"
      ? t("tournamentDetail.publicPages.schedule.closesRelative", { relative })
      : t("tournamentDetail.publicPages.schedule.startsRelative", { relative });
  };

  const isNow = (segment: PhaseSegment) => segment.state === "current" && !segment.windowClosed;
  const label = (segment: PhaseSegment) => (
    <>
      {t(`common.statusBadge.${segment.status}`)}
      {segment.windowClosed ? (
        <Eyebrow className="ml-1.5">{t("tournamentDetail.publicPages.schedule.closed")}</Eyebrow>
      ) : null}
    </>
  );

  return (
    <div id={id} className={cn("scroll-mt-28", className)}>
      <ol aria-label={t("tournamentDetail.publicPages.schedule.title")}>
        {segments.map((segment, index) => {
          const now = isNow(segment);
          const isLast = index === segments.length - 1;
          const startText = stamp(segment.startsAt);
          const countdownText = countdown(segment);
          return (
            <li
              key={segment.status}
              aria-current={segment.state === "current" ? "step" : undefined}
              className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3"
            >
              <div className="flex flex-col items-center pt-1.5">
                <span
                  aria-hidden
                  className={cn(
                    "size-2.5 shrink-0 rounded-full",
                    now
                      ? "bg-[color:var(--aqt-teal)] ring-[3px] ring-[color:var(--aqt-overlay-2)]"
                      : segment.state === "upcoming"
                        ? "border border-[color:var(--aqt-border)]"
                        : "bg-[color:var(--aqt-fg-faint)]"
                  )}
                />
                {isLast ? null : (
                  <Separator orientation="vertical" className="mt-1 h-auto flex-1" />
                )}
              </div>
              <div
                className={cn(
                  "flex min-w-0 flex-wrap items-baseline justify-between gap-x-3",
                  isLast ? "pb-0" : "pb-3"
                )}
              >
                <span
                  className={cn(
                    "text-sm",
                    now
                      ? "font-semibold text-[color:var(--aqt-teal)]"
                      : segment.state === "upcoming"
                        ? "text-[color:var(--aqt-fg-dim)]"
                        : "text-[color:var(--aqt-fg-muted)]"
                  )}
                >
                  {label(segment)}
                </span>
                <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                  {countdownText ??
                    (segment.startsAt === null ? (
                      nowText
                    ) : startText ? (
                      <time dateTime={segment.startsAt}>{startText}</time>
                    ) : null)}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
