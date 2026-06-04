"use client";

import { useEffect, useState } from "react";

import { isUrgent, remainingMs } from "../_lib/draft-logic";

interface DraftClockProps {
  expiresAt: string | null;
  paused: boolean;
}

/**
 * Local countdown from an absolute server deadline — no per-second server
 * ticks. At zero it shows "autopicking…" and waits for the server event.
 */
export function DraftClock({ expiresAt, paused }: DraftClockProps) {
  // `now` stays null until the first interval tick (avoids synchronous setState
  // in the effect and any SSR/hydration time mismatch).
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (paused || !expiresAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [paused, expiresAt]);

  if (paused) {
    return <span className="font-mono tabular-nums text-amber-400">paused</span>;
  }
  if (!expiresAt || now === null) {
    return <span className="font-mono tabular-nums text-[var(--aqt-fg-muted)]">--</span>;
  }

  const ms = remainingMs(expiresAt, now);
  if (ms <= 0) {
    return <span className="font-mono tabular-nums text-rose-500">autopicking…</span>;
  }
  const seconds = Math.ceil(ms / 1000);
  const className = isUrgent(ms)
    ? "font-mono tabular-nums text-rose-500 animate-pulse"
    : "font-mono tabular-nums text-[var(--aqt-teal)]";
  return <span className={className}>{seconds}s</span>;
}
