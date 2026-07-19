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

/**
 * Outcome of a patch attempt:
 *  - "applied":      the cached snapshot was patched in place — no refetch.
 *  - "unregistered": no reducer is registered under this resource name.
 *  - "uncached":     nothing is cached under the query key yet, so the caller
 *                    should seed a snapshot (refetch) before patching.
 */
export type PatchOutcome = "applied" | "unregistered" | "uncached";

const reducers = new Map<string, PatchReducer<unknown, Record<string, unknown>>>();

/**
 * Register the reducer for a patchable realtime resource. A consumer calls this
 * once (at module load) to declare how a realtime event folds into its cached
 * read model. The query key is supplied per call to applyResourcePatch, so a
 * resource whose cache key carries more than one id (e.g. tournament + workspace)
 * is supported. Registering the same resource again replaces the reducer.
 */
export function registerRealtimeResource<TSnapshot, TData = Record<string, unknown>>(
  resource: string,
  reduce: PatchReducer<TSnapshot, TData>,
): void {
  reducers.set(resource, reduce as unknown as PatchReducer<unknown, Record<string, unknown>>);
}

/**
 * Apply a realtime event to the cached snapshot at queryKey using the resource's
 * registered reducer, returning the outcome so the caller can fall back
 * (buffer + refetch) when there is no snapshot to patch yet. Never throws for an
 * unregistered resource or an uncached key.
 */
export function applyResourcePatch(
  queryClient: QueryClient,
  params: { resource: string; queryKey: QueryKey; event: RealtimeEventEnvelope },
): PatchOutcome {
  const reduce = reducers.get(params.resource);
  if (!reduce) {
    return "unregistered";
  }
  if (queryClient.getQueryData(params.queryKey) === undefined) {
    return "uncached";
  }
  queryClient.setQueryData(params.queryKey, (snapshot: unknown) =>
    snapshot == null ? snapshot : reduce(snapshot, params.event),
  );
  return "applied";
}
