"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { isUrgent, remainingMs } from "../_lib/draft-logic";
import { accentToken, type DraftAccent } from "../_lib/draft-visual";

interface DraftClockRingProps {
  expiresAt: string | null;
  paused: boolean;
  totalSeconds: number;
  accent: DraftAccent;
}

const SIZE = 88;
const STROKE = 6;
const R = (SIZE - STROKE) / 2;
const C = 2 * Math.PI * R;

export function DraftClockRing({ expiresAt, paused, totalSeconds, accent }: DraftClockRingProps) {
  const t = useTranslations();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
  }, [expiresAt]);

  useEffect(() => {
    if (paused || !expiresAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [paused, expiresAt]);

  const ms = expiresAt && now != null ? remainingMs(expiresAt, now) : null;
  const seconds = ms == null ? null : Math.ceil(ms / 1000);
  const frac = ms == null || totalSeconds <= 0 ? 0 : Math.min(1, ms / (totalSeconds * 1000));
  const urgent = ms != null && isUrgent(ms);
  const color = paused ? "var(--aqt-amber)" : accentToken(accent);

  return (
    <div className="relative grid place-items-center" style={{ width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE} className="-rotate-90" aria-hidden>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="var(--aqt-border)" strokeWidth={STROKE} />
        <circle
          cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke={color} strokeWidth={STROKE}
          strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - frac)}
          className="transition-[stroke-dashoffset] duration-200 motion-reduce:transition-none"
        />
      </svg>
      <span
        className={`absolute font-onest text-xl font-semibold tabular-nums ${urgent ? "animate-pulse motion-reduce:animate-none" : ""}`}
        style={{ color }}
      >
        {paused ? t("draft.clock.pauseCompact") : seconds == null ? "--" : `${seconds}`}
      </span>
    </div>
  );
}
