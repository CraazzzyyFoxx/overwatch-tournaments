import { apiFetch } from "@/lib/api/fetch";
import type { AuthProfile } from "@/stores/auth-profile.store";

/** Verbatim `GET /api/v1/auth/me` body. Every field past `username` is optional
 *  on purpose: an older identity-svc omits the newer ones and the mapping below
 *  must not turn that into a crash. */
type AuthProfileResponse = {
  id?: number | null;
  username: string;
  avatar_url?: string | null;
  roles?: string[];
  permissions?: string[];
  denies?: string[];
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
    rbac_roles?: string[];
    rbac_permissions?: string[];
  }>;
};

export function mapAuthProfile(data: AuthProfileResponse): AuthProfile {
  const linkedPlayers = (data.linked_players ?? []).map((player) => ({
    playerId: player.player_id,
    playerName: player.player_name,
    isPrimary: player.is_primary,
    linkedAt: player.linked_at
  }));

  return {
    id: data.id ?? null,
    username: data.username,
    avatarUrl: data.avatar_url ?? null,
    roles: data.roles ?? [],
    permissions: data.permissions ?? [],
    denies: data.denies ?? [],
    isSuperuser: data.is_superuser ?? false,
    workspaces: (data.workspaces ?? []).map((ws) => ({
      workspace_id: ws.workspace_id,
      slug: ws.slug,
      roles: ws.rbac_roles ?? [],
      permissions: ws.rbac_permissions ?? []
    })),
    linkedPlayers,
    primaryLinkedPlayer: linkedPlayers.find((player) => player.isPrimary) ?? linkedPlayers[0]
  };
}

/**
 * Raw `/api/v1/auth/me` response, never thrown and never auto-refreshed.
 *
 * `skipRefreshRetry`: /me is the one request whose 401/403 IS the answer, so
 * the caller has to see the refresh outcome itself — apiFetch's built-in retry
 * collapses "session is dead" and "refresh failed transiently" into the same
 * 401, and it also fires the global logout event, which must not happen just
 * because an anonymous visitor asked who they are.
 *
 * `token` omitted means "read the access cookie" (both renderers); pass one
 * explicitly on the server, where the caller already has the cookie in hand.
 */
export function fetchAuthProfileResponse(token?: string): Promise<Response> {
  return apiFetch("/api/v1/auth/me", { token, skipRefreshRetry: true, throwOnError: false });
}
