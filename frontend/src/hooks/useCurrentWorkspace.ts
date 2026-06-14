import { useMemo } from "react";

import { getDefaultDivisionGrid } from "@/lib/division-grid";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

export function useCurrentWorkspaceId(): number | null {
  return useWorkspaceStore((s) => s.currentWorkspaceId);
}

export function useDivisionGrid(): DivisionGrid {
  const workspace = useWorkspaceStore((s) => s.getCurrentWorkspace());
  const tiers = workspace?.default_division_grid_version?.tiers;
  return useMemo(() => (tiers ? { tiers } : getDefaultDivisionGrid()), [tiers]);
}

export function useDivisionGridVersion(): DivisionGridVersion | null {
  return useWorkspaceStore((s) => s.getCurrentWorkspace()?.default_division_grid_version ?? null);
}
