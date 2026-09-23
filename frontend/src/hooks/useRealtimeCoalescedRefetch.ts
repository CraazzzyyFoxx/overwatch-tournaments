"use client";

import { useEffect, useRef } from "react";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import {
  type Coalescer,
  createLeadingCoalescer,
  createTrailingCoalescer,
} from "@/lib/realtime/coalesce";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

export interface RealtimeCoalescedRefetchOptions<TData> {
  /**
   * Called on every matching event. Decide whether/what to accumulate into
   * `pending` (a ref this callback may freely mutate -- same shape every
   * existing consumer already used: a pending reason, a pending live_count,
   * or nothing at all), then call `schedule()` if a flush should happen.
   * Return without calling `schedule()` to ignore the event.
   */
  onEvent: (event: RealtimeEventEnvelope<TData>, schedule: () => void) => void;
  /** Runs at flush time -- the actual refetch/invalidate. */
  onFlush: () => void;
  /**
   * Runs instead of `onFlush` for the leading catch-up coalescer (see
   * `catchUpMs`) when provided -- for consumers whose (re)subscribe catch-up
   * plan is broader than (or otherwise different from) a normal flush's plan.
   * Omit to run `onFlush` for catch-up too (every consumer before this option
   * existed did exactly that).
   */
  onCatchUp?: () => void;
  /** 0 = no coalescing, flush immediately (matches today's hub-subscriptions consumer). */
  minDelayMs: number;
  /** Upper bound of the per-mount random offset added to minDelayMs. Omit or 0 for no jitter. */
  jitterMs?: number;
  /** Leading-edge coalescer window for the (re)subscribe/reconnect signal. Omit to skip catch-up entirely. */
  catchUpMs?: number;
}

/**
 * Shared shape behind every thin-signal realtime consumer: subscribe,
 * accumulate a pending update via a caller-supplied reducer (`onEvent`),
 * flush it through a per-mount-jittered trailing coalescer, and optionally
 * run a leading "catch-up" coalescer on (re)subscribe.
 *
 * Also owns the reconnect safety net (design doc §4.3/§7 D9): on
 * `reconnecting -> connected` it schedules a flush through the SAME jittered
 * trailing coalescer a normal event would use, never an immediate bypass --
 * an immediate refetch here would reproduce, at the moment of a mass
 * reconnect after a gateway restart, exactly the synchronized-herd pattern
 * the jitter exists to prevent.
 */
export function useRealtimeCoalescedRefetch<TData = Record<string, unknown>>(
  topic: string | null | undefined,
  options: RealtimeCoalescedRefetchOptions<TData>,
): void {
  const { onEvent, onFlush, onCatchUp, minDelayMs, jitterMs = 0, catchUpMs } = options;

  const stateRef = useRef({ onEvent, onFlush, onCatchUp });
  useEffect(() => {
    stateRef.current = { onEvent, onFlush, onCatchUp };
  });

  const catchUp = useRef<Coalescer | null>(null);
  useEffect(() => {
    if (catchUpMs == null) return;
    const coalescer = createLeadingCoalescer(
      () => (stateRef.current.onCatchUp ?? stateRef.current.onFlush)(),
      catchUpMs,
    );
    catchUp.current = coalescer;
    return () => {
      coalescer.cancel();
      catchUp.current = null;
    };
  }, [topic, catchUpMs]);

  const trailing = useRef<Coalescer | null>(null);
  useEffect(() => {
    const delay = minDelayMs + (jitterMs > 0 ? Math.floor(Math.random() * jitterMs) : 0);
    const coalescer = createTrailingCoalescer(() => stateRef.current.onFlush(), delay);
    trailing.current = coalescer;
    return () => {
      coalescer.cancel();
      trailing.current = null;
    };
  }, [topic, minDelayMs, jitterMs]);

  useRealtimeTopic<TData>(
    topic,
    (event) => {
      stateRef.current.onEvent(event, () => trailing.current?.schedule());
    },
    [],
    () => {
      catchUp.current?.schedule();
    },
  );

  // Reconnect safety-net (design §4.3, §7/D9): schedule a flush through the
  // SAME jittered trailing coalescer on reconnecting -> connected, never an
  // immediate bypass -- see the function docstring above.
  const connectionState = useRealtimeStore((state) => state.connectionState);
  const prevConnectionState = useRef(connectionState);
  useEffect(() => {
    if (prevConnectionState.current === "reconnecting" && connectionState === "connected") {
      trailing.current?.schedule();
    }
    prevConnectionState.current = connectionState;
  }, [connectionState]);
}
