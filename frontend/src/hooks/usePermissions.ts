"use client";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

export type AppRole = "admin" | "tournament_organizer" | "moderator" | "user";

const resourcesWithCrud = [
  "workspace",
  "workspace_member",
  "api_key",
  "user",
  "role",
  "tournament",
  "stage",
  "team",
  "player",
  "match",
  "standing",
  "registration_form",
  "registration",
  "registration_status",
  "balancer",
  "custom_game",
  "analytics",
  "achievement",
  "division_grid",
  "log",
  "discord_channel",
  "challonge",
  "asset",
  "tournament_link",
  "announcement",
] as const;

type CrudResource = (typeof resourcesWithCrud)[number];
type CrudAction = "read" | "create" | "update" | "delete";
type CrudPermission = `${CrudResource}.${CrudAction}`;

type SpecialPermission =
  | "admin.*"
  | "audit.read"
  // Read and delete only, mirroring the catalog: nobody writes an inbox row by
  // hand, and a "delete" here is the retire on the operator screen.
  | "notification.read"
  | "notification.delete"
  | "permission.read"
  | "auth_user.read"
  | "auth_user.update"
  | "oauth_connection.read"
  | "oauth_connection.delete"
  | "registration.approve"
  | "registration.reject"
  | "registration.check_in"
  | "rank.read"
  | "rank.update"
  | "subscription.read"
  | "subscription.update"
  | "stream.read"
  | "stream.update"
  | "account.avatar"
  | "account.rename"
  | "account.social"
  | "registration.self_register"
  | "workspace.self_create";

export type AppPermission = CrudPermission | SpecialPermission;

type AdminRouteAccessOptions = {
  permissions?: AppPermission[];
  workspaceId?: number | null;
  globalOnly?: boolean;
  workspaceAdminVisible?: boolean;
  superuserOnly?: boolean;
};

export type PermissionProfile = {
  isSuperuser: boolean;
  roles: string[];
  permissions: string[];
  denies?: string[];
  workspaces: Array<{
    workspace_id: number;
    permissions: string[];
  }>;
};

function isAdminPanelRole(role: string): boolean {
  return role === "admin" || role === "tournament_organizer" || role === "moderator";
}

function workspaceHasPermission(
  workspace: PermissionProfile["workspaces"][number] | undefined,
  permission: AppPermission,
): boolean {
  // RBAC permissions are the only grant; "admin.*" is the workspace-wide wildcard.
  return (
    workspace?.permissions.includes("admin.*") ||
    workspace?.permissions.includes(permission) ||
    false
  );
}

// Resources whose grants are member-level capabilities, not administration.
// Hosting a mix is something a plain workspace member is trusted with, so the
// grant must not hand out admin-panel entry: the "any non-read permission means
// management" shortcut below is only sound for genuinely administrative
// resources.
const NON_ADMIN_PANEL_RESOURCES: Record<string, true> = { custom_game: true };

function permissionGrantsAdminPanelAccess(permission: string): boolean {
  const [resource] = permission.split(".");
  if (NON_ADMIN_PANEL_RESOURCES[resource]) return false;
  return permission === "admin.*" || !permission.endsWith(".read");
}

function workspaceHasAnyManagementPermission(
  workspace: PermissionProfile["workspaces"][number] | undefined,
): boolean {
  if (!workspace) return false;
  return workspace.permissions.some(permissionGrantsAdminPanelAccess);
}

export function hasAdminPanelAccessForProfile(
  profile: PermissionProfile | undefined,
  workspaceId?: number | null,
): boolean {
  if (!profile) return false;
  if (profile.isSuperuser || profile.roles.some(isAdminPanelRole)) {
    return true;
  }
  if (profile.permissions.some(permissionGrantsAdminPanelAccess)) {
    return true;
  }

  if (workspaceId == null) {
    return profile.workspaces.some(workspaceHasAnyManagementPermission);
  }

  const workspace = profile.workspaces.find((candidate) => candidate.workspace_id === workspaceId);
  return workspaceHasAnyManagementPermission(workspace);
}

export function hasWorkspacePermissionForProfile(
  profile: PermissionProfile | undefined,
  workspaceId: number,
  permission: AppPermission,
): boolean {
  if (!profile) return false;
  if (profile.isSuperuser || profile.roles.includes("admin") || profile.permissions.includes("admin.*")) {
    return true;
  }
  if (profile.permissions.includes(permission)) {
    return true;
  }
  const workspace = profile.workspaces.find((candidate) => candidate.workspace_id === workspaceId);
  return workspaceHasPermission(workspace, permission);
}

export function canAccessAnyPermissionForProfile(
  profile: PermissionProfile | undefined,
  permissions: AppPermission[],
  workspaceId?: number | null,
): boolean {
  if (!profile) return false;
  if (profile.isSuperuser || profile.roles.some(isAdminPanelRole) || profile.permissions.includes("admin.*")) {
    return true;
  }
  if (workspaceId == null) {
    return (
      permissions.some((permission) => profile.permissions.includes(permission)) ||
      profile.workspaces.some((workspace) => workspace.permissions.includes("admin.*")) ||
      profile.workspaces.some((workspace) =>
        permissions.some((permission) => workspaceHasPermission(workspace, permission)),
      )
    );
  }
  return permissions.some((permission) =>
    hasWorkspacePermissionForProfile(profile, workspaceId, permission),
  );
}

export function usePermissions() {
  const user = useAuthProfileStore((s) => s.user);
  const status = useAuthProfileStore((s) => s.status);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const isLoaded = status !== "idle" && status !== "loading";
  const isAuthenticated = status === "authenticated";
  const hasAdminPanelRole = user ? user.isSuperuser || user.roles.some(isAdminPanelRole) : false;

  const hasWildcard =
    (user?.isSuperuser ?? false) ||
    (user?.roles.includes("admin") ?? false) ||
    (user?.permissions.includes("admin.*") ?? false);

  const hasRole = (role: AppRole): boolean => {
    if (!isAuthenticated || !user) return false;
    if (user.isSuperuser || user.roles.includes("admin")) return true;
    return user.roles.includes(role);
  };

  const hasAnyRole = (roles: AppRole[]): boolean => roles.some((role) => hasRole(role));
  const hasAllRoles = (roles: AppRole[]): boolean => roles.every((role) => hasRole(role));

  const hasPermission = (permission: AppPermission): boolean => {
    if (!isAuthenticated) return false;
    if (hasWildcard) return true;
    return user?.permissions.includes(permission) ?? false;
  };

  const hasAnyPermission = (permissions: AppPermission[]): boolean =>
    permissions.some((permission) => hasPermission(permission));

  // Negative RBAC: an allow-by-default capability (e.g. "account.avatar",
  // "account.social") is usable unless it's in the user's deny list.
  const isDenied = (capability: string): boolean =>
    user?.denies?.includes(capability) ?? false;

  const canUseCapability = (capability: string): boolean =>
    isAuthenticated && !isDenied(capability);

  const hasAllPermissions = (permissions: AppPermission[]): boolean =>
    permissions.every((permission) => hasPermission(permission));

  const hasWorkspacePermission = (workspaceId: number, permission: AppPermission): boolean => {
    if (!isAuthenticated || !user) return false;
    return hasWorkspacePermissionForProfile(user, workspaceId, permission);
  };

  const hasAnyWorkspacePermission = (permissions: AppPermission[]): boolean => {
    if (!isAuthenticated || !user) return false;
    if (hasWildcard) return true;
    return (
      user.workspaces?.some((workspace) =>
        permissions.some((permission) => workspaceHasPermission(workspace, permission)),
      ) ?? false
    );
  };

  const isWorkspaceAdmin = (workspaceId: number): boolean => {
    if (!isAuthenticated || !user) return false;
    if (user.isSuperuser) return true;
    const workspace = user.workspaces?.find((candidate) => candidate.workspace_id === workspaceId);
    return workspaceHasAnyManagementPermission(workspace);
  };

  const canManageAnyWorkspace = (): boolean => {
    if (!isAuthenticated || !user) return false;
    if (user.isSuperuser) return true;
    return user.workspaces?.some(workspaceHasAnyManagementPermission) ?? false;
  };

  const getAdminWorkspaceIds = (): number[] => {
    if (!isAuthenticated || !user) return [];
    return (
      user.workspaces
        ?.filter(workspaceHasAnyManagementPermission)
        .map((workspace) => workspace.workspace_id) ?? []
    );
  };

  const canAccessPermission = (
    permission: AppPermission,
    workspaceId: number | null | undefined = currentWorkspaceId,
  ): boolean => {
    if (workspaceId == null) {
      return hasPermission(permission);
    }
    return hasWorkspacePermission(workspaceId, permission);
  };

  const canAccessAnyPermission = (
    permissions: AppPermission[],
    workspaceId: number | null | undefined = currentWorkspaceId,
  ): boolean => {
    if (!isAuthenticated || !user) return false;
    return canAccessAnyPermissionForProfile(user, permissions, workspaceId);
  };

  const canAccessAdminRoute = ({
    permissions = [],
    workspaceId = currentWorkspaceId,
    globalOnly = false,
    workspaceAdminVisible = false,
    superuserOnly = false,
  }: AdminRouteAccessOptions): boolean => {
    if (!isAuthenticated || !user) return false;
    if (superuserOnly) return user.isSuperuser;
    if (!hasAdminPanelAccessForProfile(user, globalOnly ? null : workspaceId)) return false;

    let hasAccess = false;

    if (permissions.length > 0) {
      hasAccess ||= globalOnly
        ? hasAdminPanelRole || hasAnyPermission(permissions)
        : canAccessAnyPermission(permissions, workspaceId);
    }

    if (workspaceAdminVisible) {
      hasAccess ||= workspaceId == null ? canManageAnyWorkspace() : isWorkspaceAdmin(workspaceId);
    }

    if (permissions.length === 0 && !workspaceAdminVisible) {
      hasAccess = hasAdminPanelRole || canManageAnyWorkspace();
    }

    return hasAccess;
  };

  return {
    isLoaded,
    isAuthenticated,
    hasRole,
    hasAnyRole,
    hasAllRoles,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
    isDenied,
    canUseCapability,
    hasWorkspacePermission,
    hasAnyWorkspacePermission,
    isWorkspaceAdmin,
    canManageAnyWorkspace,
    getAdminWorkspaceIds,
    canAccessPermission,
    canAccessAnyPermission,
    canAccessAdminRoute,
    isSuperuser: user?.isSuperuser ?? false,
    isAdmin: hasRole("admin"),
    isOrganizer: hasRole("tournament_organizer"),
    isModerator: hasRole("moderator"),
    hasAdminPanelRole,
  };
}
