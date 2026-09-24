"use client";

import { useTranslations } from "next-intl";

import { usePickCountdown } from "@/hooks/usePickCountdown";
import { isUrgent } from "@/lib/draft/logic";
import { cn } from "@/lib/utils";
import type { DraftPick } from "@/types/draft.types";

interface DraftClockRingProps {
  pick: DraftPick | null;
  paused: boolean;
  totalSeconds: number;
  /**
   * Once the main clock expired (`pick.overtime_started_at`), `clock_expires_at`
   * holds the OVERTIME deadline, so the arc is measured against this instead.
   */
  overtimeSeconds?: number;
  /** Arc and digits while the clock runs normally; urgency, overtime and pause override it. */
  color?: string;
  /** `md`: 88px standalone ring; `sm`: the 52px ring of the clock strip. */
  size?: "md" | "sm";
}

const GEOMETRY = {
  md: { size: 88, stroke: 6 },
  sm: { size: 52, stroke: 3.5 }
} as const;
/** Seconds at which the clock announces itself. A 250ms live region is unusable. */
const ANNOUNCE_AT = [30, 10, 5];

export function DraftClockRing({
  pick,
  paused,
  totalSeconds,
  overtimeSeconds = 0,
  color = "var(--aqt-teal)",
  size = "md"
}: Readonly<DraftClockRingProps>) {
  const t = useTranslations();
  // `ms` stays null for the first render, so SSR and hydration agree on "--".
  const { ms, overtime, text } = usePickCountdown(pick, paused);
  const { size: box, stroke } = GEOMETRY[size];
  const radius = (box - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  // Its own region, and derived: the text flips exactly when the phase does,
  // and React skips identical writes, so screen readers hear "overtime" once
  // per flip instead of after every 30/10/5s tick of the threshold region.
  const phaseAnnouncement = overtime ? t("draft.clock.overtime") : "";

  const seconds = ms == null ? null : Math.ceil(ms / 1000);
  // In overtime the arc measures the grace period, not the pick time it already
  // spent — against `pick_time_seconds` a 15s overtime would render as a sliver.
  const total = overtime ? overtimeSeconds : totalSeconds;
  const frac = ms == null || total <= 0 ? 0 : Math.min(1, ms / (total * 1000));
  const urgent = ms != null && isUrgent(ms);
  // Colour, not only the pulse: under prefers-reduced-motion the animation is
  // suppressed, so motion alone would leave no urgency cue at all.
  const tone = paused ? "var(--aqt-amber)" : overtime || urgent ? "var(--aqt-live)" : color;
  const label = paused
    ? t("draft.clock.paused")
    : seconds == null
      ? t("draft.clock.idle")
      : overtime
        ? `${t("draft.clock.overtime")} · ${t("draft.clock.remaining", { seconds })}`
        : t("draft.clock.remaining", { seconds });

  // Derived, not stateful: the text only exists while `seconds` sits on a
  // threshold, and React skips identical text writes, so the live region gets
  // exactly one announcement per threshold instead of one every 250ms tick.
  const announcement =
    !paused && seconds != null && ANNOUNCE_AT.includes(seconds)
      ? t("draft.clock.remaining", { seconds })
      : "";

  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: box, height: box }}>
      <svg width={box} height={box} className="-rotate-90" aria-hidden>
        <circle
          cx={box / 2}
          cy={box / 2}
          r={radius}
          fill="none"
          stroke="var(--aqt-border-2)"
          strokeWidth={stroke}
        />
        <circle
          cx={box / 2}
          cy={box / 2}
          r={radius}
          fill="none"
          stroke={tone}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - frac)}
          className="transition-[stroke-dashoffset] duration-200 motion-reduce:transition-none"
        />
      </svg>
      <span
        role="timer"
        aria-label={label}
        className={cn(
          "absolute flex flex-col items-center font-semibold tabular-nums",
          size === "md" ? "font-onest text-xl" : "text-sm font-bold",
          urgent && "animate-pulse motion-reduce:animate-none"
        )}
        style={{ color: tone }}
      >
        {/* 52px holds no word: the small ring stays digits; amber and the label say "paused". */}
        {paused && size === "md" ? t("draft.clock.pauseCompact") : (text ?? "--")}
        {overtime && !paused && size === "md" && (
          <span className="text-label font-bold uppercase tracking-label">{t("draft.clock.overtime")}</span>
        )}
      </span>
      <span className="sr-only" aria-live="polite">
        {announcement}
      </span>
      <span className="sr-only" aria-live="polite">
        {phaseAnnouncement}
      </span>
    </div>
  );
}
