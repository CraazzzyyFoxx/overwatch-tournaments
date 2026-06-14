import Cookies from "js-cookie";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AuthProfile } from "@/stores/auth-profile.store";
import { Workspace } from "@/types/workspace.types";
import workspaceService from "@/services/workspace.service";

const WORKSPACE_COOKIE = "aqt-workspace-id";

type WorkspaceState = {
  workspaces: Workspace[];
  currentWorkspaceId: number | null;
  isLoading: boolean;

  fetchWorkspaces: () => Promise<void>;
  setCurrentWorkspace: (id: number) => void;
  getCurrentWorkspace: () => Workspace | undefined;
};

export function filterAccessibleWorkspaces(
  workspaces: Workspace[],
  authStatus: string,
  user?: AuthProfile
): Workspace[] {
  if (authStatus !== "authenticated" || !user) {
    return workspaces;
  }

  if (user.isSuperuser) {
    return workspaces;
  }

  const allowedWorkspaceIds = new Set(user.workspaces.map((workspace) => workspace.workspace_id));
  return workspaces.filter((workspace) => allowedWorkspaceIds.has(workspace.id));
}

export function resolveCurrentWorkspaceId(
  workspaces: Workspace[],
  currentWorkspaceId: number | null
): number | null {
  if (workspaces.length === 0) {
    return null;
  }

  const hasCurrentWorkspace =
    currentWorkspaceId !== null &&
    workspaces.some((workspace) => workspace.id === currentWorkspaceId);

  return hasCurrentWorkspace ? currentWorkspaceId : (workspaces[0]?.id ?? null);
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      workspaces: [],
      currentWorkspaceId: null,
      isLoading: false,

      fetchWorkspaces: async () => {
        if (get().isLoading) return;
        set({ isLoading: true });
        try {
          const workspaces = await workspaceService.getAll();
          const current = get().currentWorkspaceId;
          const nextId = resolveCurrentWorkspaceId(workspaces, current);
          if (nextId !== null) {
            Cookies.set(WORKSPACE_COOKIE, String(nextId), { sameSite: "lax" });
          } else {
            Cookies.remove(WORKSPACE_COOKIE);
          }
          set({
            workspaces,
            currentWorkspaceId: nextId,
            isLoading: false
          });
        } catch {
          set({ isLoading: false });
        }
      },

      setCurrentWorkspace: (id: number) => {
        Cookies.set(WORKSPACE_COOKIE, String(id), { sameSite: "lax" });
        set({ currentWorkspaceId: id });
      },

      getCurrentWorkspace: () => {
        const { workspaces, currentWorkspaceId } = get();
        return workspaces.find((w) => w.id === currentWorkspaceId);
      }
    }),
    {
      name: "aqt-workspace",
      partialize: (state) => ({ currentWorkspaceId: state.currentWorkspaceId })
    }
  )
);
