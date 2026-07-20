"use client";

import { useEffect } from "react";

import { useThemeScopeStore } from "@/stores/theme-scope.store";
import type { Workspace } from "@/types/workspace.types";

/**
 * Scopes the site theme to a tournament's owning workspace while its routes are
 * mounted, so a tournament always paints its own brand regardless of which
 * workspace the viewer has selected. Clears the scope on unmount so navigating
 * away restores the viewer's palette.
 *
 * The owning workspace is resolved server-side (flash-free SSR seed lives in the
 * `(site)` layout); this component only drives the client-side sync for soft
 * navigations and workspace switches.
 */
export function TournamentThemeScope({ workspace }: { workspace: Workspace | null }) {
  const setScopedWorkspace = useThemeScopeStore((s) => s.setScopedWorkspace);

  useEffect(() => {
    setScopedWorkspace(workspace);
    return () => setScopedWorkspace(null);
  }, [workspace, setScopedWorkspace]);

  return null;
}
