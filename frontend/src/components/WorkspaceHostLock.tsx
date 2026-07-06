"use client";

import { useEffect } from "react";

import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Locks the client-side workspace store to the host's workspace on a tenant
 * (white-label) host, so client-side `apiFetch` scoping and {@link
 * WorkspaceThemeSync} match the server-side host lock (`x-owt-workspace-id`).
 *
 * `workspaceId` is resolved server-side in the `(site)` layout from the
 * authoritative middleware header; `null` on the apex/platform host clears any
 * lock so normal cookie-driven switching resumes.
 */
export function WorkspaceHostLock({ workspaceId }: { workspaceId: number | null }) {
  const setHostLock = useWorkspaceStore((s) => s.setHostLock);

  useEffect(() => {
    setHostLock(workspaceId);
  }, [workspaceId, setHostLock]);

  return null;
}
