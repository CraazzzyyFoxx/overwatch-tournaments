"use client";

import { useQueries, type UseQueryResult } from "@tanstack/react-query";

import balancerAdminService from "@/services/balancer-admin.service";
import type { AdminRegistration } from "@/types/balancer-admin.types";

/** One row per profile, the first node's entry winning: the node list is newest first, and the newest entry decides (Decision 9). */
function combine(results: UseQueryResult<AdminRegistration[]>[]) {
  const seen = new Set<number>();
  const rows = results.flatMap((result) => result.data ?? []).filter((row) => !seen.has(row.id) && seen.add(row.id));
  return {
    data: results.some((result) => result.data) ? rows : undefined,
    isLoading: results.some((result) => result.isLoading),
    isError: results.some((result) => result.isError),
    refetch: () => results.forEach((result) => void result.refetch())
  };
}

/**
 * The entries of every registration node feeding a formation, as one list. `queryKey` names each node's cache entry, so
 * a write that patches a node's entries patches this list.
 */
export function usePoolRegistrations({
  tournamentId,
  nodeIds,
  includeDeleted,
  queryKey
}: Readonly<{
  tournamentId: number | null;
  nodeIds: readonly number[];
  includeDeleted: boolean;
  queryKey: (nodeId: number) => readonly unknown[];
}>) {
  return useQueries({
    queries: nodeIds.map((nodeId) => ({
      queryKey: queryKey(nodeId),
      queryFn: () =>
        balancerAdminService.listRegistrations(tournamentId as number, nodeId, { include_deleted: includeDeleted }),
      enabled: tournamentId !== null,
      refetchOnWindowFocus: false
    })),
    combine
  });
}
