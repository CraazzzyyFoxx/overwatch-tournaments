"use client";

import { useEffect } from "react";

import { getAccessTokenCookie, refreshAccessToken } from "@/lib/auth/tokens";
import { getTokenExpMs } from "@/lib/auth/jwt";

const REFRESH_SKEW_MS = 60_000; // refresh ~1 min before the token expires
const MIN_DELAY_MS = 5_000; // never schedule a busy-loop
const FALLBACK_DELAY_MS = 5 * 60_000; // when `exp` can't be decoded
const RETRY_DELAY_MS = 30_000; // back off after a transient refresh error
// Every tab reads the SAME access cookie, so every tab derives the same absolute
// refresh deadline and fires at the same instant — a self-inflicted thundering
// herd on /auth/refresh that races the rotation (one prod session accumulated
// 1368 rotations). Spread the wake-ups; the 60s skew leaves ≥40s of headroom.
const REFRESH_JITTER_MS = 20_000;

function computeDelay(token: string | undefined): number {
  const jitter = Math.random() * REFRESH_JITTER_MS;
  if (!token) return MIN_DELAY_MS + jitter;
  const expMs = getTokenExpMs(token);
  if (expMs === undefined) return FALLBACK_DELAY_MS + jitter;
  return Math.max(MIN_DELAY_MS, expMs - Date.now() - REFRESH_SKEW_MS) + jitter;
}

// Proactively refreshes the access token shortly before it expires, so an
// active tab never has to recover from an expired token reactively. Background
// tabs throttle timers heavily, so this is complemented by a visibility-change
// refresh in AuthBootstrap. Self-reschedules off each new token's `exp`.
export function useProactiveTokenRefresh(enabled: boolean, onSessionDead: () => void): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      return;
    }

    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const schedule = (delay: number): void => {
      if (cancelled) return;
      timer = setTimeout(() => {
        void tick();
      }, delay);
    };

    const tick = async (): Promise<void> => {
      if (cancelled) return;
      const outcome = await refreshAccessToken();
      if (cancelled) return;

      if (outcome.status === "unauthenticated") {
        onSessionDead();
        return; // session is dead — stop scheduling
      }
      if (outcome.status === "error") {
        schedule(RETRY_DELAY_MS);
        return;
      }
      schedule(computeDelay(outcome.token));
    };

    void (async () => {
      const token = await getAccessTokenCookie();
      schedule(computeDelay(token));
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, onSessionDead]);
}
