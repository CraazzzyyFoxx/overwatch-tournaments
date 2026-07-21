"use client";

import { useEffect } from "react";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { applyWorkspacePalette, deriveWorkspacePalette } from "@/lib/workspace-theme";

/**
 * Applies the site palette on the client.
 *
 * Custom workspace branding is tenant-only: only a locked tenant (subdomain /
 * custom-domain) host paints its workspace's palette. The shared platform (apex)
 * host never customizes, so this clears any inherited palette back to the default
 * tokens there.
 *
 * On a tenant host the `(site)` layout SSR-seeds the palette for a flash-free
 * first paint; this keeps it in sync once the store has loaded (the host-locked
 * workspace only becomes resolvable after `fetchWorkspaces`). It never clears the
 * SSR seed in the hydration gap before the locked workspace is known.
 */
export function WorkspaceThemeSync() {
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const hostLockedWorkspaceId = useWorkspaceStore((s) => s.hostLockedWorkspaceId);

  useEffect(() => {
    const el = document.querySelector<HTMLElement>(".site-theme");
    if (!el) return;

    // Shared platform host: no customization — ensure the default tokens apply.
    if (hostLockedWorkspaceId == null) {
      applyWorkspacePalette(el, null);
      return;
    }

    // Tenant host: theme from the host-locked workspace once it's loaded. Until
    // then keep the SSR seed rather than clearing it in the hydration gap.
    const locked = workspaces.find((w) => w.id === hostLockedWorkspaceId);
    if (!locked) return;
    applyWorkspacePalette(el, deriveWorkspacePalette(locked));
  }, [hostLockedWorkspaceId, workspaces]);

  return null;
}
