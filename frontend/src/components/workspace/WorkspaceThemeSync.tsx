"use client";

import { useEffect } from "react";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { applyWorkspacePalette, deriveWorkspacePalette } from "@/lib/workspace/theme";

/**
 * Applies the site palette on the client.
 *
 * Custom workspace branding is tenant-only: only a locked tenant (subdomain /
 * custom-domain) host paints its workspace's palette. The shared platform (apex)
 * host never customizes, so this clears any inherited palette back to the default
 * tokens there.
 *
 * On a tenant host the `(site)` layout SSR-seeds the palette on `.site-theme`
 * for a flash-free first paint; this keeps it in sync once the store has loaded
 * (the host-locked workspace only becomes resolvable after `fetchWorkspaces`).
 * It never clears the SSR seed in the hydration gap before the locked workspace
 * is known.
 *
 * The palette is applied to BOTH `.site-theme` and `document.body`: Radix
 * portals (Popover, Select, Dialog, …) render into `document.body`, outside
 * `.site-theme`, so portaled UI only themes via body-level vars. Body (not the
 * root element) is the mirror target because the `.dark` class on `<body>`
 * re-declares the shadcn triplets there, shadowing anything set higher up;
 * inline vars on body win over its own class. Portals mount after hydration,
 * so the body-level palette is always in place by the time they show.
 */
export function WorkspaceThemeSync() {
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const hostLockedWorkspaceId = useWorkspaceStore((s) => s.hostLockedWorkspaceId);

  useEffect(() => {
    const scoped = document.querySelector<HTMLElement>(".site-theme");
    const targets = scoped ? [document.body, scoped] : [document.body];

    // Shared platform host: no customization — ensure the default tokens apply.
    if (hostLockedWorkspaceId == null) {
      for (const el of targets) applyWorkspacePalette(el, null);
      return;
    }

    // Tenant host: theme from the host-locked workspace once it's loaded. Until
    // then keep the SSR seed rather than clearing it in the hydration gap.
    const locked = workspaces.find((w) => w.id === hostLockedWorkspaceId);
    if (!locked) return;
    const palette = deriveWorkspacePalette(locked);
    for (const el of targets) applyWorkspacePalette(el, palette);
  }, [hostLockedWorkspaceId, workspaces]);

  return null;
}
