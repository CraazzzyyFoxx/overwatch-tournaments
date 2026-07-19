"use client";

import { useEffect } from "react";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { applyWorkspacePalette, deriveWorkspacePalette } from "@/lib/workspace-theme";

/**
 * Keeps the main-site palette in sync with the selected workspace on the client.
 *
 * The `(site)` layout SSR-seeds the palette onto the `.site-theme` wrapper for a
 * flash-free first paint. Switching workspaces only updates the store + cookie
 * (no `router.refresh()`), so this component re-derives and imperatively applies
 * the palette whenever the current workspace changes.
 *
 * It intentionally does nothing until the store has loaded its workspaces, so the
 * SSR seed is never cleared in the gap before hydration completes.
 */
export function WorkspaceThemeSync() {
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);

  useEffect(() => {
    // Store not hydrated yet — leave the SSR seed untouched.
    if (workspaces.length === 0) return;

    const el = document.querySelector<HTMLElement>(".site-theme");
    if (!el) return;

    const current = workspaces.find((w) => w.id === currentWorkspaceId) ?? null;
    applyWorkspacePalette(el, deriveWorkspacePalette(current));
  }, [currentWorkspaceId, workspaces]);

  return null;
}
