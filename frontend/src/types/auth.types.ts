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

export interface ApiKeyLimits {
  requests_per_minute: number;
  jobs_per_day: number;
  concurrent_jobs: number;
  max_upload_bytes: number;
  max_players: number;
}

export interface ApiKeyConfigPolicy {
  allowed_keys: string[];
  /** @deprecated Algorithm choice is no longer configurable; field kept for backward compat. */
  allowed_algorithms?: string[];
  max_values: Record<string, number>;
}

export interface AccountApiKey {
  id: number;
  name: string;
  workspace_id: number;
  public_id: string;
  scopes: string[];
  limits: ApiKeyLimits;
  config_policy: ApiKeyConfigPolicy;
  expires_at?: string | null;
  revoked_at?: string | null;
  last_used_at?: string | null;
  created_at: string;
  updated_at?: string | null;
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

export interface OAuthConnection {
  provider: OAuthProviderName;
  provider_user_id: string;
  email?: string | null;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
  raw_data?: Record<string, unknown>;
}
