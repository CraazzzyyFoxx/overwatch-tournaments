import { create } from "zustand";
import { getTokenFromCookies, refreshAccessToken } from "@/lib/auth-tokens";

export type WorkspaceRbac = {
  workspace_id: number;
  slug: string;
  memberRole: string;
  roles: string[];
  permissions: string[];
};

export type AuthLinkedPlayer = {
  playerId: number;
  playerName: string;
  isPrimary: boolean;
  linkedAt: string;
};

export type AuthProfile = {
  id?: number | null;
  username: string;
  avatarUrl?: string | null;
  roles: string[];
  permissions: string[];
  isSuperuser: boolean;
  workspaces: WorkspaceRbac[];
  linkedPlayers: AuthLinkedPlayer[];
  primaryLinkedPlayer?: AuthLinkedPlayer;
};

export type AuthProfileStatus = "idle" | "loading" | "authenticated" | "anonymous" | "error";

type AuthProfileState = {
  status: AuthProfileStatus;
  user?: AuthProfile;
  error?: string;
  lastFetchedAt?: number;

  fetchMe: (opts?: { force?: boolean; staleMs?: number }) => Promise<void>;
  clear: () => void;
};


export const useAuthProfileStore = create<AuthProfileState>((set, get) => ({
  status: "idle",
  user: undefined,
  error: undefined,
  lastFetchedAt: undefined,

  clear: () => set({ status: "anonymous", user: undefined, error: undefined, lastFetchedAt: Date.now() }),

  fetchMe: async (opts) => {
    const { status, lastFetchedAt } = get();
    if (status === "loading") {
      return;
    }

    const isFresh =
      typeof opts?.staleMs === "number" &&
      typeof lastFetchedAt === "number" &&
      Date.now() - lastFetchedAt < opts.staleMs;

    if (!opts?.force && isFresh && (status === "authenticated" || status === "anonymous")) {
      return;
    }

    if (!opts?.force && status === "authenticated" && typeof opts?.staleMs !== "number") {
      return;
    }

    const isInitialLoad = status === "idle";

    if (isInitialLoad) {
      set({ status: "loading", error: undefined });
    } else {
      set({ error: undefined });
    }

    try {
      const token = await getTokenFromCookies("aqt_access_token");
      let res = await fetch("/api/auth/me", {
        method: "GET",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      // If 401, attempt token refresh and retry once
      if (res.status === 401 && typeof window !== "undefined") {
        const newToken = await refreshAccessToken();
        if (newToken) {
          res = await fetch("/api/auth/me", {
            method: "GET",
            headers: { Authorization: `Bearer ${newToken}` },
          });
        }
      }

      const fetchedAt = Date.now();

      if (res.status === 401) {
        set({ status: "anonymous", user: undefined, error: undefined, lastFetchedAt: fetchedAt });
        return;
      }

      if (!res.ok) {
        set({
          status: "error",
          user: undefined,
          error: `Failed to fetch profile (${res.status})`,
          lastFetchedAt: fetchedAt
        });
        return;
      }

      const data: {
        id?: number | null;
        username: string;
        avatar_url?: string | null;
        roles?: string[];
        permissions?: string[];
        is_superuser?: boolean;
        linked_players?: Array<{
          player_id: number;
          player_name: string;
          is_primary: boolean;
          linked_at: string;
        }>;
        workspaces?: Array<{
          workspace_id: number;
          slug: string;
          role: string;
          rbac_roles?: string[];
          rbac_permissions?: string[];
        }>;
      } = await res.json();
      const linkedPlayers = (data.linked_players ?? []).map((player) => ({
        playerId: player.player_id,
        playerName: player.player_name,
        isPrimary: player.is_primary,
        linkedAt: player.linked_at
      }));
      const primaryLinkedPlayer =
        linkedPlayers.find((player) => player.isPrimary) ?? linkedPlayers[0];
      set({
        status: "authenticated",
        user: {
          id: data.id ?? null,
          username: data.username,
          avatarUrl: data.avatar_url ?? null,
          roles: data.roles ?? [],
          permissions: data.permissions ?? [],
          isSuperuser: data.is_superuser ?? false,
          workspaces: (data.workspaces ?? []).map((ws) => ({
            workspace_id: ws.workspace_id,
            slug: ws.slug,
            memberRole: ws.role,
            roles: ws.rbac_roles ?? [],
            permissions: ws.rbac_permissions ?? [],
          })),
          linkedPlayers,
          primaryLinkedPlayer,
        },
        error: undefined,
        lastFetchedAt: fetchedAt
      });
    } catch (e) {
      set({
        status: "error",
        user: undefined,
        error: e instanceof Error ? e.message : "Failed to fetch profile",
        lastFetchedAt: Date.now()
      });
    }
  }
}));
