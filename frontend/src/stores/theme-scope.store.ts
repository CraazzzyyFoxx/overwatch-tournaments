import { create } from "zustand";

import type { Workspace } from "@/types/workspace.types";

/**
 * Route-scoped site theme override.
 *
 * The `(site)` layout themes `.site-theme` from the *viewer's* selected
 * workspace. Some routes render a resource owned by a *different* workspace
 * (e.g. viewing a tournament owned by another org) and must paint that owner's
 * brand instead of the viewer's. Such routes push the owning workspace here and
 * clear it on unmount; {@link WorkspaceThemeSync} reads it as the authoritative
 * override (unless a tenant host has locked the workspace).
 */
type ThemeScopeState = {
  scopedWorkspace: Workspace | null;
  setScopedWorkspace: (workspace: Workspace | null) => void;
};

export const useThemeScopeStore = create<ThemeScopeState>((set) => ({
  scopedWorkspace: null,
  setScopedWorkspace: (workspace) => set({ scopedWorkspace: workspace }),
}));
