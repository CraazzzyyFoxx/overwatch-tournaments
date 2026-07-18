"use client";

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import type { RealtimeEventEnvelope } from "@/types/realtime.types";

/**
 * Fold one realtime event into a cached snapshot, immutably and idempotently:
 * re-applying the same event (deduped by event_id) must converge to the same
 * state. This is the per-resource half of "patch data from WS instead of
 * refetching the full read model".
 */
export type PatchReducer<TSnapshot, TData = Record<string, unknown>> = (
  snapshot: TSnapshot,
  event: RealtimeEventEnvelope<TData>,
) => TSnapshot;

export type RealtimeResource<TSnapshot, TData = Record<string, unknown>> = {
  /** The react-query key holding the snapshot this resource patches. */
  queryKey: (resourceId: number) => QueryKey;
  /** Fold a single realtime event into the cached snapshot. */
  reduce: PatchReducer<TSnapshot, TData>;
};

/**
 * Outcome of a patch attempt:
 *  - "applied":      the cached snapshot was patched in place — no refetch.
 *  - "unregistered": no resource is registered under this name.
 *  - "uncached":     the resource is registered but nothing is cached yet, so the
 *                    caller should seed a snapshot (refetch) before patching.
 */
export type PatchOutcome = "applied" | "unregistered" | "uncached";

const registry = new Map<string, RealtimeResource<unknown, Record<string, unknown>>>();

/**
 * Register a patchable realtime resource. A consumer calls this once (at module
 * load) to declare how its cached read model is keyed and how a realtime event
 * folds into it — the general, reusable half of the mechanism. Registering the
 * same resource again replaces the prior definition.
 */
export function registerRealtimeResource<TSnapshot, TData = Record<string, unknown>>(
  resource: string,
  definition: RealtimeResource<TSnapshot, TData>,
): void {
  registry.set(
    resource,
    definition as unknown as RealtimeResource<unknown, Record<string, unknown>>,
  );
}

/**
 * Apply a realtime event to the cached snapshot of a registered resource,
 * returning the outcome so the caller can fall back (buffer + refetch) when
 * there is no snapshot to patch yet. A no-op that never throws for events whose
 * resource is unregistered or uncached.
 */
export function applyResourcePatch(
  queryClient: QueryClient,
  params: { resource: string; resourceId: number; event: RealtimeEventEnvelope },
): PatchOutcome {
  const definition = registry.get(params.resource);
  if (!definition) {
    return "unregistered";
  }

  const queryKey = definition.queryKey(params.resourceId);
  if (queryClient.getQueryData(queryKey) === undefined) {
    return "uncached";
  }

  queryClient.setQueryData(queryKey, (snapshot: unknown) =>
    snapshot == null ? snapshot : definition.reduce(snapshot, params.event),
  );
  return "applied";
}
