"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { resolveToolState, type ToolContextStatus } from "@/app/balancer/tool-context";
import { useSyncActiveWorkspace } from "@/hooks/useSyncActiveWorkspace";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { BalancerTournamentSummary } from "@/types/balancer-admin.types";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";

export interface ToolContext {
  status: ToolContextStatus;
  summary: BalancerTournamentSummary | null;
}

/**
 * Resolves the balancer tool's tournament context from `?tournament=` (D29).
 *
 * Fetches the team.read-gated summary (workspace resolved server-side from the
 * tournament, so the call is safe while the store still points elsewhere), then
 * one-way aligns the workspace store via `useSyncActiveWorkspace`. `status`
 * stays "loading" until the store matches the summary's workspace: `apiFetch`
 * injects `workspace_id` from the store, so consumers must not fire data
 * requests before alignment. WorkspaceBootstrap's global invalidation on the
 * switch is accepted behavior (D29/arbiter) — do not "fix" it here.
 */
export function useToolContext(): ToolContext {
  const tournamentId = useBalancerTournamentId();
  const query = useQuery({
    queryKey: balancerQueryKeys.tournamentSummary(tournamentId),
    queryFn: () => balancerAdminService.getTournamentSummary(tournamentId as number),
    enabled: tournamentId != null,
    // Errors are terminal states (forbidden / pointer screen) — surface them
    // immediately instead of spinning through retries.
    retry: false,
    staleTime: 60_000
  });
  const summary = query.data ?? null;

  useSyncActiveWorkspace(summary?.workspace_id);
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const hostLockedWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);

  // Alignment is required once per tournament, then latched: after entry the
  // sync hook deliberately does not fight a manual workspace switch, so a
  // reactive check would demote a once-ready context back to "loading" forever.
  // Render-phase setState with a guard is React's documented pattern for
  // derived-state latching (refs must not be touched during render).
  const [alignedFor, setAlignedFor] = useState<number | null>(null);
  if (
    summary != null &&
    (hostLockedWorkspaceId != null || currentWorkspaceId === summary.workspace_id) &&
    alignedFor !== tournamentId
  ) {
    setAlignedFor(tournamentId);
  }
  const aligned = summary == null || alignedFor === tournamentId;

  const status = resolveToolState(tournamentId, query);
  return { status: status === "ready" && !aligned ? "loading" : status, summary };
}
