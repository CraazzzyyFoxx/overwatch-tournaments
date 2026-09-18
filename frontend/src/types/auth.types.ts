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

/**
 * The three enforcement scopes a metered call is subject to. A principal is
 * charged against its own scope (`key` for an API key, `session` for a signed-in
 * member) *and* against the workspace pool the whole tenant shares, so a 429
 * always names which of the two refused.
 */
export type QuotaScope = "workspace" | "key" | "session";

/** The five dimensions, in the order every quota table declares them. */
export const QUOTA_DIMENSIONS = [
  "requests_per_minute",
  "heavy_per_day",
  "concurrent_heavy",
  "max_upload_bytes",
  "max_items_per_request"
] as const;

export type QuotaDimension = (typeof QUOTA_DIMENSIONS)[number];

/**
 * One scope's effective ceilings next to what is already spent. A `null` limit
 * is unlimited, not zero; `*_reset_in` is seconds until the counter's window
 * rolls over, and is `null` when nothing is counted yet.
 */
export interface QuotaScopeUsage {
  scope: QuotaScope;
  requests_per_minute: number | null;
  requests_used: number;
  requests_reset_in: number | null;
  heavy_per_day: number | null;
  heavy_used: number;
  heavy_reset_in: number | null;
  concurrent_heavy: number | null;
  concurrent_used: number;
  max_upload_bytes: number | null;
  max_items_per_request: number | null;
}

export interface QuotaUsage {
  plan_slug: string | null;
  workspace_id: number | null;
  scopes: QuotaScopeUsage[];
  /**
   * Editable policy per scope. Empty on reads that only report consumption.
   */
  policy: QuotaScopePolicy[];
}

/**
 * An override write. An absent or `null` dimension means *inherit* — from the
 * workspace override, then from the plan — never zero, which would block the
 * operation outright. An all-`null` payload deletes the override row.
 */
export interface QuotaLimitsPayload {
  requests_per_minute?: number | null;
  heavy_per_day?: number | null;
  concurrent_heavy?: number | null;
  max_upload_bytes?: number | null;
  max_items_per_request?: number | null;
}

/**
 * What is stored for one scope, and the ceiling a write must stay under.
 *
 * `QuotaScopeUsage` carries the *effective* number, which cannot tell "the plan
 * grants 600" apart from "someone wrote 600 here" — so an editor seeded from it
 * would turn a glance into a permanent override, and an editor seeded from
 * nothing deletes the row on its first save.
 *
 * `inherited` is the same bound the server enforces for this scope: a value
 * above it is a raise, and a raise is superuser-only.
 */
export interface QuotaScopePolicy {
  scope: QuotaScope;
  override: QuotaLimitsPayload;
  inherited: QuotaLimitsPayload;
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
