import { useEffect } from "react";

import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Syncs the active workspace to the owning workspace of the resource the viewer
 * opened (a tournament, its analytics, etc.), so the rest of the app — nav,
 * data scoping, the workspace switcher — follows that resource.
 *
 * Apex-only: a no-op on a locked tenant (subdomain / custom-domain) host, where
 * the workspace is fixed by the request host. Keyed on `workspaceId` alone, so a
 * manual switch while on the page is not fought, and it never re-writes when the
 * active workspace already matches.
 */
export function useSyncActiveWorkspace(workspaceId: number | null | undefined): void {
  useEffect(() => {
    if (workspaceId == null) return;
    const { currentWorkspaceId, hostLockedWorkspaceId, setCurrentWorkspace } =
      useWorkspaceStore.getState();
    if (hostLockedWorkspaceId != null) return;
    if (currentWorkspaceId === workspaceId) return;
    setCurrentWorkspace(workspaceId);
  }, [workspaceId]);
}
