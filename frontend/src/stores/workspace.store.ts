import Cookies from "js-cookie";
import { create } from "zustand";
import type { AuthProfile } from "@/stores/auth-profile.store";
import { Workspace } from "@/types/workspace.types";
import workspaceService from "@/services/workspace.service";

// Canonical workspace cookie name. LEGACY_WORKSPACE_COOKIE is read as a
// fallback during the aqt->owt rename so an active workspace selection is
// not lost; it is never written.
export const WORKSPACE_COOKIE = "owt-workspace-id";
export const LEGACY_WORKSPACE_COOKIE = "aqt-workspace-id";
// Persist for a year so the active workspace survives browser restarts and is
// present on the very first server render of each new session — otherwise SSR
// reads no workspace and server components render unscoped (cross-workspace) data.
const WORKSPACE_COOKIE_TTL_DAYS = 365;
// Key of the removed zustand `persist` bucket. The workspace id had three
// persisted homes (this bucket, the cookie, and the server's read of the
// cookie); only the cookie can be read by BOTH renderers, so it is now the
// single one and the store is a runtime cache hydrated from it. Dropped on
// load so a stale localStorage id cannot outlive the migration.
const OBSOLETE_PERSIST_KEY = "aqt-workspace";

// Client-side hydration of the single persisted source. `null` on the server:
// server components read the cookie through `getServerWorkspaceId` instead,
// and seeding this module-level store per request would leak one visitor's
// scope into another's render.
function workspaceIdFromCookie(): number | null {
  if (typeof document === "undefined") return null;
  try {
    window.localStorage.removeItem(OBSOLETE_PERSIST_KEY);
  } catch {
    // Storage disabled (private mode / blocked cookies): nothing to clean up.
  }
  const raw = Cookies.get(WORKSPACE_COOKIE) ?? Cookies.get(LEGACY_WORKSPACE_COOKIE);
  const id = raw ? Number(raw) : NaN;
  return Number.isFinite(id) ? id : null;
}

type WorkspaceState = {
  workspaces: Workspace[];
  currentWorkspaceId: number | null;
  /**
   * On a tenant (white-label) host the workspace is fixed by the request host,
   * not the cookie/store. When set, the store scope is locked to this id so
   * client-side `apiFetch` and the theme sync match the server-side host lock,
   * switching is disabled, and the workspace cookie is left untouched. `null`
   * on the apex/platform host.
   */
  hostLockedWorkspaceId: number | null;
  isLoading: boolean;

  fetchWorkspaces: () => Promise<void>;
  setCurrentWorkspace: (id: number) => void;
  setHostLock: (id: number | null) => void;
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

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  workspaces: [],
  currentWorkspaceId: workspaceIdFromCookie(),
  hostLockedWorkspaceId: null,
  isLoading: false,

  fetchWorkspaces: async () => {
    if (get().isLoading) return;
    set({ isLoading: true });
    try {
      // `all`: the switcher must reach the member's own hidden/unverified
      // workspaces, which the public directory (`scope=public`) drops.
      const workspaces = await workspaceService.getAll("all");
      const locked = get().hostLockedWorkspaceId;
      const current = get().currentWorkspaceId;
      const nextId = locked ?? resolveCurrentWorkspaceId(workspaces, current);
      // On a locked tenant host the scope comes from the request host, not
      // the cookie — never touch the workspace cookie there.
      if (locked == null) {
        if (nextId !== null) {
          Cookies.set(WORKSPACE_COOKIE, String(nextId), {
            sameSite: "lax",
            expires: WORKSPACE_COOKIE_TTL_DAYS
          });
        } else {
          Cookies.remove(WORKSPACE_COOKIE);
        }
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
    // On a locked tenant (white-label) host the workspace is fixed by the
    // request host; ignore attempts to switch.
    if (get().hostLockedWorkspaceId != null) return;
    Cookies.set(WORKSPACE_COOKIE, String(id), {
      sameSite: "lax",
      expires: WORKSPACE_COOKIE_TTL_DAYS
    });
    set({ currentWorkspaceId: id });
  },

  setHostLock: (id: number | null) => {
    // Lock (tenant host) or clear (apex) the client-side workspace scope.
    // Forcing currentWorkspaceId corrects it even if fetchWorkspaces ran
    // first, so client apiFetch/theme-sync align with the SSR host lock.
    if (id != null) {
      // Also drop any workspace cookie a race-ahead fetchWorkspaces may have
      // written, so the "no cookie on a locked host" invariant holds
      // regardless of effect order (SSR scopes by the host header anyway).
      Cookies.remove(WORKSPACE_COOKIE);
      set({ hostLockedWorkspaceId: id, currentWorkspaceId: id });
    } else {
      set({ hostLockedWorkspaceId: null });
    }
  },

  getCurrentWorkspace: () => {
    const { workspaces, currentWorkspaceId } = get();
    return workspaces.find((w) => w.id === currentWorkspaceId);
  }
}));
