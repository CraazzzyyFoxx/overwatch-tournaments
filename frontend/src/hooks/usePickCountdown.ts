"use client";

import { useEffect, useState } from "react";

import { remainingMs } from "@/lib/draft/logic";
import type { DraftPick } from "@/types/draft.types";

export interface PickCountdown {
  /** `null` until mounted (SSR renders no guessed time) or without a running clock. */
  ms: number | null;
  /** The pick is past its main clock and burning its overtime grace. */
  overtime: boolean;
  /** `m:ss`, prefixed `+` in overtime; `null` whenever `ms` is. */
  text: string | null;
}

export function formatClock(ms: number, overtime: boolean): string {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${overtime ? "+" : ""}${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * One ticking countdown for every surface that shows the pick clock (strip,
 * island, pill, banner), against the server's absolute deadline. Stops ticking
 * while paused or without a deadline.
 */
export function usePickCountdown(pick: DraftPick | null, paused: boolean): PickCountdown {
  const [now, setNow] = useState<number | null>(null);
  const expiresAt = pick?.clock_expires_at ?? null;

  useEffect(() => {
    const initialId = window.setTimeout(() => setNow(Date.now()), 0);
    const intervalId = !paused && expiresAt ? window.setInterval(() => setNow(Date.now()), 250) : null;
    return () => {
      window.clearTimeout(initialId);
      if (intervalId != null) window.clearInterval(intervalId);
    };
  }, [paused, expiresAt]);

  const overtime = pick?.overtime_started_at != null;
  const ms = expiresAt && now != null ? remainingMs(expiresAt, now) : null;
  return { ms, overtime, text: ms == null ? null : formatClock(ms, overtime) };
}
