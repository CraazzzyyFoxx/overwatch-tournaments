import { apiFetch } from "@/lib/api-fetch";
import type { PaginatedResponse } from "@/types/pagination.types";
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

type ListParams = {
  page?: number;
  per_page?: number;
  sort?: string;
  order?: string;
};

export type RbacUserDeny = {
  permission_id: number;
  name: string;
  resource: string;
  action: string;
  description?: string | null;
  /** Scope this deny to a single workspace; null/absent = global deny. */
  workspace_id?: number | null;
};

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

/** Build a `?key=value` query string, skipping null/undefined/empty values. */
function listQuery(params?: Record<string, unknown>): string {
  if (!params) return "";
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    searchParams.set(key, String(value));
  }
  const suffix = searchParams.toString();
  return suffix ? `?${suffix}` : "";
}

async function rbacFetch<T>(
  path: string,
  init?: { method?: string; body?: unknown; query?: Record<string, unknown> }
): Promise<T> {
  const response = await apiFetch(`/api/auth${path}`, {
    method: init?.method,
    body: init?.body,
    query: init?.query,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

type UserListParams = ListParams & {
  search?: string;
  role_id?: number;
  is_active?: boolean;
  is_superuser?: boolean;
  workspace_id?: number;
};

type RoleListParams = ListParams & {
  search?: string;
  workspace_id?: number | null;
};

type PermissionListParams = ListParams & {
  search?: string;
  workspace_id?: number | null;
};

type OAuthConnectionListParams = ListParams & {
  search?: string;
  provider?: string;
};

type SessionListParams = ListParams & {
  search?: string;
  user_id?: number;
  status?: "active" | "revoked" | "expired";
};

export const rbacService = {
  listUsers(params?: UserListParams): Promise<PaginatedResponse<AuthAdminUser>> {
    return rbacFetch<PaginatedResponse<AuthAdminUser>>(`/rbac/users${listQuery(params)}`).then(
      (page) => ({ ...page, results: page.results.map(normalizeAuthAdminUser) })
    );
  },

  /** Fetch every matching auth user (for comboboxes/dropdowns, not paginated tables). */
  async listUsersAll(params?: Omit<UserListParams, "page" | "per_page">): Promise<AuthAdminUser[]> {
    const page = await this.listUsers({ ...params, per_page: -1 });
    return page.results;
  },

  getUser(userId: number) {
    return rbacFetch<AuthAdminUserDetail>(`/rbac/users/${userId}`).then(normalizeAuthAdminUserDetail);
  },

  /** Permanently delete an auth account (superuser only; self-delete rejected server-side). */
  deleteUser(userId: number) {
    return rbacFetch<void>(`/rbac/users/${userId}`, {
      method: "DELETE",
    });
  },

  listRoles(params?: RoleListParams): Promise<PaginatedResponse<RbacRole>> {
    return rbacFetch<PaginatedResponse<RbacRole>>(`/rbac/roles${listQuery(params)}`);
  },

  /** Fetch every role in scope (for selectors/matrices, not paginated tables). */
  async listRolesAll(params?: Omit<RoleListParams, "page" | "per_page">): Promise<RbacRole[]> {
    const page = await this.listRoles({ ...params, per_page: -1 });
    return page.results;
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

  listPermissions(params?: PermissionListParams): Promise<PaginatedResponse<RbacPermission>> {
    return rbacFetch<PaginatedResponse<RbacPermission>>(`/rbac/permissions${listQuery(params)}`);
  },

  /** Fetch every permission in scope (for the role permission matrix, not paginated tables). */
  async listPermissionsAll(
    params?: Omit<PermissionListParams, "page" | "per_page">
  ): Promise<RbacPermission[]> {
    const page = await this.listPermissions({ ...params, per_page: -1 });
    return page.results;
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

  // Per-user permission denies (negative RBAC). Each call returns the user's full deny list.
  getUserDenies(userId: number) {
    return rbacFetch<RbacUserDeny[]>(`/rbac/users/${userId}/denies`);
  },

  /** `workspaceId` omitted/null denies the permission globally; a concrete id scopes the deny to that workspace. */
  addUserDeny(userId: number, permissionId: number, workspaceId?: number | null) {
    return rbacFetch<RbacUserDeny[]>(`/rbac/users/${userId}/denies`, {
      method: "POST",
      body: { permission_id: permissionId, workspace_id: workspaceId ?? null },
    });
  },

  /** Must match the scope of the deny being removed: omit `workspaceId` to remove the global deny. */
  removeUserDeny(userId: number, permissionId: number, workspaceId?: number | null) {
    return rbacFetch<RbacUserDeny[]>(`/rbac/users/${userId}/denies/${permissionId}`, {
      method: "DELETE",
      query: workspaceId ? { workspace_id: workspaceId } : undefined,
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

  listOAuthConnections(
    params?: OAuthConnectionListParams
  ): Promise<PaginatedResponse<OAuthConnectionAdmin>> {
    return rbacFetch<PaginatedResponse<OAuthConnectionAdmin>>(
      `/rbac/oauth-connections${listQuery(params)}`
    );
  },

  deleteOAuthConnection(connectionId: number) {
    return rbacFetch<void>(`/rbac/oauth-connections/${connectionId}`, {
      method: "DELETE",
    });
  },

  listSessions(params?: SessionListParams): Promise<PaginatedResponse<AdminAuthSession>> {
    return rbacFetch<PaginatedResponse<AdminAuthSession>>(`/rbac/sessions${listQuery(params)}`);
  },
};
