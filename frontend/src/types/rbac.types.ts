export interface RbacPermission {
  id: number;
  name: string;
  resource: string;
  action: string;
  description?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface RbacRole {
  id: number;
  name: string;
  description?: string | null;
  is_system: boolean;
  workspace_id?: number | null;
  created_at: string;
  updated_at?: string | null;
}

export interface RbacRoleDetail extends RbacRole {
  permissions: RbacPermission[];
}

export interface AuthAdminUser {
  id: number;
  email: string;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  avatar_url?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  linked_players: AuthAdminLinkedPlayer[];
  roles: RbacRole[];
  created_at: string;
  updated_at?: string | null;
}

export interface AuthAdminLinkedPlayer {
  player_id: number;
  player_name: string;
  is_primary: boolean;
  linked_at: string;
}

export interface AuthAdminUserDetail extends AuthAdminUser {
  effective_permissions: string[];
}

export interface AssignRolePayload {
  user_id: number;
  role_id: number;
}

export interface AssignLinkedPlayerPayload {
  player_id: number;
  is_primary: boolean;
}

export interface UpsertRolePayload {
  name: string;
  description?: string | null;
  permission_ids: number[];
  workspace_id?: number | null;
}

export type OAuthProvider = "discord" | "twitch" | "battlenet" | "google" | "github";

export interface OAuthConnectionAdmin {
  id: number;
  provider: OAuthProvider;
  provider_user_id: string;
  email?: string | null;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
  created_at: string;
  updated_at?: string | null;
  auth_user_id: number;
  auth_user_email?: string | null;
  auth_user_username?: string | null;
  token_expires_at?: string | null;
}

export type AdminSessionStatus = "active" | "revoked" | "expired";

export interface AdminAuthSession {
  session_id: string;
  user_id: number;
  email?: string | null;
  username?: string | null;
  status: AdminSessionStatus;
  login_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at?: string | null;
  user_agent?: string | null;
  ip_address?: string | null;
}
