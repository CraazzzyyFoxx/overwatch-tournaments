"use client";

import { useQueries } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/error";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import adminService from "@/services/admin.service";
import type { CareerSignalsResponse, CareerUserSignals } from "@/types/career-signals.types";

/** The endpoint takes 1..200 user ids per call. */
const CHUNK = 200;

const chunks = (userIds: readonly number[]) => {
  const sorted = [...new Set(userIds)].sort((a, b) => a - b);
  return Array.from({ length: Math.ceil(sorted.length / CHUNK) }, (_, i) => sorted.slice(i * CHUNK, (i + 1) * CHUNK));
};

// Module-level so TanStack memoizes the combined result: the table's column memo depends on it.
const combine = (results: { data?: CareerSignalsResponse; error: unknown }[]) => ({
  byUser: new Map<number, CareerUserSignals>(results.flatMap((result) => result.data?.users ?? []).map((user) => [user.user_id, user])),
  // The viewer lacks `rank.read` (403), or the game collects no career (404): the column and section stay away.
  unavailable: results.some(
    (result) => result.error instanceof ApiError && (result.error.status === 403 || result.error.status === 404)
  )
});

/**
 * The career signals of a registrations list: one batched read per chunk of ≤200 users, keyed by the chunk's sorted
 * ids, workspace and game. `unavailable` says the answer is "no", so the UI hides itself quietly.
 */
export function useCareerSignals({
  workspaceId,
  discipline,
  userIds,
  enabled
}: Readonly<{ workspaceId: number | null; discipline: string | null; userIds: readonly number[]; enabled: boolean }>) {
  const active = enabled && workspaceId !== null && discipline !== null;
  return useQueries({
    queries: chunks(userIds).map((ids) => ({
      queryKey: adminQueryKeys.rankCareerSignals(workspaceId, discipline, ids),
      queryFn: () => adminService.getCareerSignals(discipline as string, workspaceId as number, ids),
      enabled: active,
      staleTime: 60_000,
      retry: (count: number, error: unknown) =>
        !(error instanceof ApiError && (error.status === 403 || error.status === 404)) && count < 2
    })),
    combine
  });
}
