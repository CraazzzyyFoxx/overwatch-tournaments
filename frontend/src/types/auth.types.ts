export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: "bearer" | string;
}

export type AccountSessionStatus = "active" | "revoked" | "expired";

export interface AccountSession {
  session_id: string;
  is_current: boolean;
  status: AccountSessionStatus;
  login_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at?: string | null;
  user_agent?: string | null;
  ip_address?: string | null;
}

export interface AccountApiKey {
  id: number;
  name: string;
  workspace_id: number;
  public_id: string;
  owner_id: number;
  owner_username: string;
  scopes: string[];
  limits: Record<string, unknown>;
  expires_at?: string | null;
  revoked_at?: string | null;
  last_used_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

/**
 * Create payload for a workspace-scoped API key.
 *
 * `scopes` are RBAC permission names (`"team.create"`, `"admin.*"`) — the same
 * vocabulary the backend catalog uses, intersected server-side with what the
 * caller actually holds. An empty list is accepted and produces a key that
 * authenticates but passes no permission check.
 */
export interface AccountApiKeyCreateInput {
  name: string;
  workspace_id: number;
  scopes: string[];
  expires_at?: string | null;
}

export interface AccountApiKeyCreateResponse {
  api_key: AccountApiKey;
  key: string;
}

export interface AuthUser {
  id: number;
  email: string;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  avatar_url?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  roles: string[];
  permissions: string[];
  linked_players: LinkedPlayer[];
  created_at: string;
  updated_at?: string | null;
}

export interface LinkedPlayer {
  player_id: number;
  player_name: string;
  is_primary: boolean;
  linked_at: string;
}

export type OAuthProviderName = "discord" | "twitch" | "battlenet";

export interface OAuthProviderAvailability {
  provider: OAuthProviderName;
}
