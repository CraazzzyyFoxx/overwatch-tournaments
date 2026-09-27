"use client";

import { useQuery } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/**
 * Cache root of the unresolved-name queue.
 *
 * The tab badge in the layout and the queue table on `unresolved` both hang
 * off it, so attaching or dismissing one name invalidates this single key and
 * both surfaces agree on the new count.
 */
export const MISS_QUEUE_KEY = adminQueryKeys.catalogAliasMisses();

/**
 * How many log names are still waiting for a decision — the number on the
 * "Unresolved names" tab. One row is requested; only `total` is read.
 */
export function useOpenMissCount(): number {
  const { data } = useQuery({
    queryKey: [...MISS_QUEUE_KEY, "open-count"],
    queryFn: () =>
      adminService.getCatalogAliasMisses({ page: 1, per_page: 1, include_resolved: false })
  });

  return data?.total ?? 0;
}
