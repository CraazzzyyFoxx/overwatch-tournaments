import { apiFetch } from "@/lib/api-fetch";
import type {
  AdminAuthSession,
  AssignLinkedPlayerPayload,
  AssignRolePayload,
  AuthAdminUser,
  AuthAdminUserDetail,
  OAuthConnectionAdmin,
  RbacPermission,
  RbacRole,
  RbacRoleDetail,
  UpsertRolePayload,
} from "@/types/rbac.types";

function normalizeAuthAdminUser(user: AuthAdminUser): AuthAdminUser {
  return {
    ...user,
    linked_players: user.linked_players ?? [],
  };
}

function normalizeAuthAdminUserDetail(user: AuthAdminUserDetail): AuthAdminUserDetail {
  return {
    ...normalizeAuthAdminUser(user),
    effective_permissions: user.effective_permissions ?? [],
  };
}

async function rbacFetch<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const response = await apiFetch("auth", path, {
    method: init?.method,
    body: init?.body,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const rbacService = {
  listUsers(params?: {
    search?: string;
    role_id?: number;
    is_active?: boolean;
    is_superuser?: boolean;
    workspace_id?: number;
  }) {
    const searchParams = new URLSearchParams();
    if (params?.search) searchParams.set("search", params.search);
    if (params?.role_id !== undefined) searchParams.set("role_id", String(params.role_id));
    if (params?.is_active !== undefined) searchParams.set("is_active", String(params.is_active));
    if (params?.is_superuser !== undefined) searchParams.set("is_superuser", String(params.is_superuser));
    if (params?.workspace_id !== undefined) searchParams.set("workspace_id", String(params.workspace_id));

    const suffix = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return rbacFetch<AuthAdminUser[]>(`/rbac/users${suffix}`).then((users) => users.map(normalizeAuthAdminUser));
  },

  getUser(userId: number) {
    return rbacFetch<AuthAdminUserDetail>(`/rbac/users/${userId}`).then(normalizeAuthAdminUserDetail);
  },

  listRoles(params?: { workspace_id?: number | null }) {
    const searchParams = new URLSearchParams();
    if (params?.workspace_id !== undefined && params.workspace_id !== null) {
      searchParams.set("workspace_id", String(params.workspace_id));
    }
    const suffix = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return rbacFetch<RbacRole[]>(`/rbac/roles${suffix}`);
  },

  getRole(roleId: number) {
    return rbacFetch<RbacRoleDetail>(`/rbac/roles/${roleId}`);
  },

  createRole(payload: UpsertRolePayload) {
    return rbacFetch<RbacRole>("/rbac/roles", {
      method: "POST",
      body: payload,
    });
  },

  updateRole(roleId: number, payload: Partial<UpsertRolePayload>) {
    return rbacFetch<RbacRole>(`/rbac/roles/${roleId}`, {
      method: "PATCH",
      body: payload,
    });
  },

  deleteRole(roleId: number) {
    return rbacFetch<void>(`/rbac/roles/${roleId}`, {
      method: "DELETE",
    });
  },

  listPermissions(params?: { workspace_id?: number | null }) {
    const searchParams = new URLSearchParams();
    if (params?.workspace_id !== undefined && params.workspace_id !== null) {
      searchParams.set("workspace_id", String(params.workspace_id));
    }
    const suffix = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return rbacFetch<RbacPermission[]>(`/rbac/permissions${suffix}`);
  },

  assignRole(payload: AssignRolePayload) {
    return rbacFetch<void>("/rbac/users/assign-role", {
      method: "POST",
      body: payload,
    });
  },

  removeRole(payload: AssignRolePayload) {
    return rbacFetch<void>("/rbac/users/remove-role", {
      method: "POST",
      body: payload,
    });
  },

  assignLinkedPlayer(userId: number, payload: AssignLinkedPlayerPayload) {
    return rbacFetch<void>(`/rbac/users/${userId}/linked-players`, {
      method: "POST",
      body: payload,
    });
  },

  removeLinkedPlayer(userId: number, playerId: number) {
    return rbacFetch<void>(`/rbac/users/${userId}/linked-players/${playerId}`, {
      method: "DELETE",
    });
  },

  listOAuthConnections(params?: { search?: string; provider?: string }) {
    const searchParams = new URLSearchParams();
    if (params?.search) searchParams.set("search", params.search);
    if (params?.provider) searchParams.set("provider", params.provider);

    const suffix = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return rbacFetch<OAuthConnectionAdmin[]>(`/rbac/oauth-connections${suffix}`);
  },

  deleteOAuthConnection(connectionId: number) {
    return rbacFetch<void>(`/rbac/oauth-connections/${connectionId}`, {
      method: "DELETE",
    });
  },

  listSessions(params?: { user_id?: number; search?: string; status?: "active" | "revoked" | "expired" }) {
    const searchParams = new URLSearchParams();
    if (params?.user_id !== undefined) searchParams.set("user_id", String(params.user_id));
    if (params?.search) searchParams.set("search", params.search);
    if (params?.status) searchParams.set("status", params.status);

    const suffix = searchParams.toString() ? `?${searchParams.toString()}` : "";
    return rbacFetch<AdminAuthSession[]>(`/rbac/sessions${suffix}`);
  },
};
