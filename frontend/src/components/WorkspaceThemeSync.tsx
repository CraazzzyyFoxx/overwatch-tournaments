"use client";

import { useEffect } from "react";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { useThemeScopeStore } from "@/stores/theme-scope.store";
import { applyWorkspacePalette, deriveWorkspacePalette } from "@/lib/workspace-theme";

/**
 * Keeps the main-site palette in sync with the active workspace on the client.
 *
 * The `(site)` layout SSR-seeds the palette onto the `.site-theme` wrapper for a
 * flash-free first paint. Switching workspaces only updates the store + cookie
 * (no `router.refresh()`), so this component re-derives and imperatively applies
 * the palette whenever the active workspace changes.
 *
 * A route-scoped workspace (see {@link useThemeScopeStore}) wins over the
 * viewer's selection — e.g. viewing a tournament owned by another workspace
 * paints that owner's brand. A locked tenant (white-label) host always keeps its
 * host-fixed brand, so the scope is ignored there.
 *
 * It intentionally does nothing until the store has loaded its workspaces, so the
 * SSR seed is never cleared in the gap before hydration completes.
 */
export function WorkspaceThemeSync() {
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const hostLockedWorkspaceId = useWorkspaceStore((s) => s.hostLockedWorkspaceId);
  // Subscribe for reactivity; the effect reads the *fresh* value via getState so
  // it never applies a stale scope on the mount commit (a deeper route's scope
  // effect runs before this parent effect and sets the store synchronously).
  const scopedWorkspaceReactive = useThemeScopeStore((s) => s.scopedWorkspace);

  useEffect(() => {
    const el = document.querySelector<HTMLElement>(".site-theme");
    if (!el) return;

    const scoped = useThemeScopeStore.getState().scopedWorkspace;
    if (scoped && hostLockedWorkspaceId == null) {
      applyWorkspacePalette(el, deriveWorkspacePalette(scoped));
      return;
    }

    // Store not hydrated yet — leave the SSR seed untouched.
    if (workspaces.length === 0) return;

    const current = workspaces.find((w) => w.id === currentWorkspaceId) ?? null;
    applyWorkspacePalette(el, deriveWorkspacePalette(current));
  }, [scopedWorkspaceReactive, hostLockedWorkspaceId, currentWorkspaceId, workspaces]);

  return null;
}
