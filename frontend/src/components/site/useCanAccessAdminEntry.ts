"use client";

import { usePermissions } from "@/hooks/usePermissions";
import { adminEntryPermissions } from "@/lib/auth/admin-permissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Whether the viewer gets the header's admin entry. The desktop header and the
 * mobile sheet both call this, so the rule exists once instead of being
 * re-derived per surface.
 */
export function useCanAccessAdminEntry(): boolean {
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { isOrganizer, isLoaded, canAccessAdminRoute } = usePermissions();

  // D27: organizers get the admin entry — the same predicate that used to open
  // the balancer.
  return (
    isLoaded &&
    (isOrganizer ||
      canAccessAdminRoute({
        permissions: adminEntryPermissions,
        workspaceId: currentWorkspaceId,
        workspaceAdminVisible: true
      }))
  );
}
