import { ApiError } from "@/lib/api/error";
import type { BalancerTournamentSummary } from "@/types/balancer-admin.types";

/**
 * Resolution state of the balancer tool's tournament context (D29).
 *
 * - `loading`   — summary request (or workspace-store alignment) in flight.
 * - `ready`     — summary resolved; the workspace store matches it.
 * - `missing`   — no valid `?tournament=` param: pointer screen.
 * - `forbidden` — the viewer may not read this tournament (401/403).
 * - `not_found` — the tournament does not exist (also the fallback for
 *   unexpected errors: the pointer screen is the safest generic exit).
 */
export type ToolContextStatus = "loading" | "ready" | "missing" | "forbidden" | "not_found";

/** The subset of the TanStack Query result the pure resolver depends on. */
export interface SummaryQuerySnapshot {
  data: BalancerTournamentSummary | undefined;
  isError: boolean;
  error: unknown;
}

/** Pure part of `useToolContext`: `?tournament=` param + summary query → status. */
export function resolveToolState(
  tournamentId: number | null,
  query: SummaryQuerySnapshot
): ToolContextStatus {
  if (tournamentId == null) return "missing";
  if (query.isError) {
    if (query.error instanceof ApiError && (query.error.status === 401 || query.error.status === 403)) {
      return "forbidden";
    }
    // 404, 400+not_found, or anything unexpected — all exit via the pointer screen.
    return "not_found";
  }
  return query.data !== undefined ? "ready" : "loading";
}
