import { create } from "zustand";
import { fetchAuthProfileResponse, mapAuthProfile } from "@/lib/auth/profile";
import { refreshAccessToken } from "@/lib/auth/tokens";

type WorkspaceRbac = {
  workspace_id: number;
  slug: string;
  roles: string[];
  permissions: string[];
};

type AuthLinkedPlayer = {
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
  /** Denied "resource.action" capabilities (negative RBAC). */
  denies: string[];
  isSuperuser: boolean;
  workspaces: WorkspaceRbac[];
  linkedPlayers: AuthLinkedPlayer[];
  primaryLinkedPlayer?: AuthLinkedPlayer;
};

type AuthProfileStatus = "idle" | "loading" | "authenticated" | "anonymous" | "error";

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
      let res = await fetchAuthProfileResponse();

      // 401 AND 403 both mean "no usable access token" here. /me has no
      // permission gate, so the gateway's "Not authenticated" (403 until the
      // status was corrected) and identity's 403 for a deactivated account are
      // both authentication answers, never authorization ones. Reading 403 as a
      // generic failure was the production bug: ~19% of /me calls answered 403
      // because the access cookie had simply expired (15 min), skipped the
      // refresh below, and presented a live 30-day session as logged out — users
      // then signed in by hand (491 logins from ~200 browsers in five days, one
      // of them 29 times). Both codes stay accepted so neither side's rollback
      // can resurrect that behaviour.
      if ((res.status === 401 || res.status === 403) && typeof window !== "undefined") {
        const outcome = await refreshAccessToken();
        if (outcome.status === "refreshed") {
          res = await fetchAuthProfileResponse(outcome.token);
        } else if (outcome.status === "error") {
          // Transient refresh failure (network / 5xx). Don't flip an already
          // known auth state to anonymous. On the very first load there is no
          // prior state to preserve, so surface an "error" status (recoverable
          // on the next focus/visibility revalidation, since the freshness guard
          // never short-circuits "error") instead of getting stuck in "loading".
          if (isInitialLoad) {
            set({
              status: "error",
              user: undefined,
              error: "Failed to refresh session",
              lastFetchedAt: Date.now(),
            });
          }
          return;
        }
        // outcome === "unauthenticated": fall through — `res` still carries the
        // 401/403 and we set the anonymous state below.
      }

      const fetchedAt = Date.now();

      if (res.status === 401 || res.status === 403) {
        set({ status: "anonymous", user: undefined, error: undefined, lastFetchedAt: fetchedAt });
        return;
      }

      // 5xx says the identity service is unavailable — it says nothing about WHO
      // the user is. Keep the known identity (the access cookie is still valid)
      // and let the next focus/visibility revalidation retry; only a first load,
      // which has no prior state to protect, surfaces the error.
      if (res.status >= 500) {
        if (isInitialLoad) {
          set({
            status: "error",
            user: undefined,
            error: `Failed to fetch profile (${res.status})`,
            lastFetchedAt: fetchedAt
          });
        }
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

      set({
        status: "authenticated",
        user: mapAuthProfile(await res.json()),
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
