"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useRealtimeCoalescedRefetch } from "@/hooks/useRealtimeCoalescedRefetch";
import {
  RESOURCE_QUERY_KEYS,
  ROUTE_REFRESH_RESOURCES,
  type RealtimeResource,
  type ResourceKeyContext,
  resourceQueryKeys,
} from "@/lib/realtime-resources";

/**
 * One invalidation consumer for the whole app.
 *
 * Subscribes to `<scope>:invalidation` and drops exactly the query keys the
 * event's resources name. Before this hook every domain carried its own
 * reason-to-keys map — the tournament page, the admin hub, the draft room, the
 * balancer page, notifications and streams — and those maps disagreed with the
 * gateway's and the backend's, which is how a draft pick came to evict a whole
 * tournament's HTTP cache while a balancer export evicted nothing.
 *
 * Domain topics are NOT consumed here: they carry data (patches, presence, job
 * progress) and are handled by their own hooks.
 */
export type UseInvalidationOptions = ResourceKeyContext & {
  scopeKind: "tournament" | "workspace" | "user";
  scopeId: number | null | undefined;
  /** Runs when a resource cannot be fixed by refetching (tournament.structure). */
  onRouteRefresh?: () => void;
  /** Extra work per flush, e.g. a domain hook that also holds local state. */
  onFlush?: (resources: readonly RealtimeResource[]) => void;
};

/**
 * Trailing coalescing with per-mount jitter, reused from the thin-signal
 * primitive: one bracket move fans an event to every spectator at once, and
 * refetching inline would spike the backend in lockstep. `catchUpMs` is the
 * leading window for (re)subscribe, where the plan is deliberately broader —
 * every resource of the scope, since a client that was away cannot know what
 * it missed (Redis pub/sub is at-most-once and its replay window is bounded).
 */
const MIN_DELAY_MS = 250;
const JITTER_MS = 2500;
const CATCH_UP_MS = 100;

export function useInvalidation({
  scopeKind,
  scopeId,
  onRouteRefresh,
  onFlush,
  ...keyContext
}: UseInvalidationOptions): void {
  const queryClient = useQueryClient();
  const topic = scopeId != null ? `${scopeKind}:${scopeId}:invalidation` : null;

  const pendingRef = useRef<Set<RealtimeResource>>(new Set());

  // A pending set belongs to one topic: carrying it across a scope change
  // would invalidate the new scope's keys for the old scope's event.
  useEffect(() => {
    return () => {
      pendingRef.current = new Set();
    };
  }, [topic]);

  useRealtimeCoalescedRefetch<{ resources?: string[] }>(topic, {
    minDelayMs: MIN_DELAY_MS,
    jitterMs: JITTER_MS,
    catchUpMs: CATCH_UP_MS,
    onEvent: (event, schedule) => {
      const resources = event.data?.resources;
      if (!Array.isArray(resources) || resources.length === 0) {
        return;
      }
      let known = false;
      for (const resource of resources) {
        if (resource in RESOURCE_QUERY_KEYS) {
          pendingRef.current.add(resource as RealtimeResource);
          known = true;
        }
      }
      // An unknown resource is ignored rather than escalated: this client is
      // simply older than the publisher, and the resources it DOES know are
      // still applied. Reconnect catch-up covers the rest.
      if (known) {
        schedule();
      }
    },
    onCatchUp: () => {
      if (scopeId == null) {
        return;
      }
      const all = Object.keys(RESOURCE_QUERY_KEYS) as RealtimeResource[];
      const scoped = all.filter((resource) => resource.startsWith(`${scopeKind}.`));
      for (const key of resourceQueryKeys(scoped, scopeId, keyContext)) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
    onFlush: () => {
      const resources = [...pendingRef.current];
      pendingRef.current = new Set();
      if (scopeId == null || resources.length === 0) {
        return;
      }
      for (const key of resourceQueryKeys(resources, scopeId, keyContext)) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      if (resources.some((resource) => ROUTE_REFRESH_RESOURCES[resource])) {
        onRouteRefresh?.();
      }
      onFlush?.(resources);
    },
  });
}
