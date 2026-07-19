"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

const SIZE = 64;
const STROKE = 5;
const R = (SIZE - STROKE) / 2;
const C = 2 * Math.PI * R;

interface VetoCountdownProps {
  /** Epoch-ms deadline of the current turn. */
  deadline: number;
  totalSeconds: number;
}

/**
 * Client-side turn-timer indicator: counts down from `deadline` and switches to
 * an "expired" highlight at zero. Purely informational — the backend never
 * auto-acts on expiry and neither does this component.
 */
export function VetoCountdown({ deadline, totalSeconds }: VetoCountdownProps) {
  const t = useTranslations("encounters.veto.room");
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    // Deferred first tick keeps the SSR-rendered markup hydration-safe.
    const initialId = window.setTimeout(() => setNow(Date.now()), 0);
    const intervalId = window.setInterval(() => setNow(Date.now()), 250);
    return () => {
      window.clearTimeout(initialId);
      window.clearInterval(intervalId);
    };
  }, [deadline]);

  const ms = now == null ? null : deadline - now;
  const expired = ms != null && ms <= 0;
  const seconds = ms == null ? null : Math.max(0, Math.ceil(ms / 1000));
  const frac =
    ms == null || totalSeconds <= 0 ? 0 : Math.min(1, Math.max(0, ms) / (totalSeconds * 1000));
  const color = expired ? "var(--aqt-amber)" : "var(--aqt-teal)";

  return (
    <div className="flex items-center gap-3">
      <div className="relative grid place-items-center" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} className="-rotate-90" aria-hidden>
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            stroke="var(--aqt-border)"
            strokeWidth={STROKE}
          />
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            stroke={color}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - frac)}
            className="transition-[stroke-dashoffset] duration-200 motion-reduce:transition-none"
          />
        </svg>
        <span
          className={`absolute font-onest text-lg font-semibold tabular-nums ${
            expired ? "animate-pulse motion-reduce:animate-none" : ""
          }`}
          style={{ color }}
        >
          {seconds == null ? "--" : seconds}
        </span>
      </div>
      <div className="flex flex-col">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          {t("timer.label")}
        </span>
        {expired ? (
          <span className="text-sm font-semibold text-[color:var(--aqt-amber)]">
            {t("timer.expired")}
          </span>
        ) : null}
      </div>
    </div>
  );
}
