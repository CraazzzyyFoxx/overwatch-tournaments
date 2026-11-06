import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminQueryKeys } from "@/lib/admin/query-keys";
import { divisionGridQueryKeys } from "@/lib/divisions/query-keys";
import { resolveOwnerGrid } from "@/lib/divisions/grid";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { DivisionGrid, DivisionGridVersion, Workspace } from "@/types/workspace.types";

export function useCurrentWorkspaceId(): number | null {
  return useWorkspaceStore(
    (s) => s.hostLockedWorkspaceId ?? s.entityWorkspaceId ?? s.currentWorkspaceId
  );
}

/**
 * One workspace in full, grids included: the store's list rows carry none. On the cache entry the settings pages
 * read and invalidate, so a saved change reaches every grid reader.
 */
export function useWorkspaceRead(workspaceId: number | null): Workspace | undefined {
  return useQuery({
    queryKey: adminQueryKeys.workspace(workspaceId ?? 0),
    queryFn: () => workspaceService.getById(workspaceId as number),
    enabled: workspaceId !== null
  }).data;
}

/**
 * The grid ranks of `discipline` resolve through for the current workspace (its real effective version, which
 * already carries that game's system/native fallback). While the workspace is not loaded, or the game has no
 * grid, this is an EMPTY grid: icon and label readers then render their neutral missing state — never another
 * game's crests. Without an explicit `discipline` the workspace's first enabled game is read, as before.
 */
export function useDivisionGrid(discipline?: string): DivisionGrid {
  const tiers = useDivisionGridVersion(discipline)?.tiers;
  return useMemo(() => ({ tiers: tiers ?? [] }), [tiers]);
}

export function useDivisionGridVersion(discipline?: string): DivisionGridVersion | null {
  const workspace = useWorkspaceRead(useCurrentWorkspaceId());
  return resolveOwnerGrid(workspace, discipline ?? workspace?.disciplines_enabled[0]);
}

/**
 * The grid a tournament's ranks resolve through: its pinned version, else the workspace's effective grid for the
 * game — the order `tournament_effective_version_id_expr` resolves on the backend. `pinnedVersionId` undefined is
 * unresolved owner metadata, null is "no pin"; `pinnedVersion` is the embedded pin, read instead of a fetch when it
 * matches. `null` while unresolved.
 */
export function useTournamentDivisionGridVersion(
  discipline: string | undefined,
  pinnedVersionId: number | null | undefined,
  pinnedVersion?: DivisionGridVersion | null
): DivisionGridVersion | null {
  const workspaceVersion = useDivisionGridVersion(discipline);
  const suppliedPin = pinnedVersionId != null && pinnedVersion?.id === pinnedVersionId ? pinnedVersion : null;
  const pinnedQuery = useQuery({
    queryKey: divisionGridQueryKeys.version(pinnedVersionId ?? null),
    queryFn: () => workspaceService.getDivisionGridVersion(pinnedVersionId!),
    enabled: discipline !== undefined && pinnedVersionId != null && suppliedPin === null
  });
  if (discipline === undefined || pinnedVersionId === undefined) return null;
  if (pinnedVersionId === null) return workspaceVersion;
  return suppliedPin ?? pinnedQuery.data ?? null;
}
