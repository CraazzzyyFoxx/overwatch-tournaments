"use client";

import { useMemo } from "react";

import { usePermissions } from "@/hooks/usePermissions";
import { adminEntryPermissions } from "@/lib/auth/admin-permissions";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { NAV_GROUPS, type NavGroupKey, type NavItem } from "./site-nav-groups";

export interface VisibleNavGroup {
  key: NavGroupKey;
  items: readonly NavItem[];
}

/**
 * The nav tree filtered to what the current viewer may see, group and item
 * level. Both the desktop menu and the mobile sheet call this, so the
 * permission rule exists once instead of being re-derived per surface.
 */
export function useVisibleNavGroups(): VisibleNavGroup[] {
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { isOrganizer, isLoaded, canAccessAdminRoute } = usePermissions();

  // D27: organizers get the admin entry — the same predicate that used to open
  // the balancer.
  const canAccessAdminEntry =
    isLoaded &&
    (isOrganizer ||
      canAccessAdminRoute({
        permissions: adminEntryPermissions,
        workspaceId: currentWorkspaceId,
        workspaceAdminVisible: true
      }));

  return useMemo(
    () =>
      NAV_GROUPS.filter((group) => group.key !== "organization" || canAccessAdminEntry).map(
        (group) => ({
          key: group.key,
          items: group.items.filter((item) => !item.requiresAdminAccess || canAccessAdminEntry)
        })
      ),
    [canAccessAdminEntry]
  );
}
