"use client";

import { useWorkspaceStore } from "@/stores/workspace.store";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

export type AppRole = "admin" | "tournament_organizer" | "moderator" | "user";

const resourcesWithCrud = [
  "workspace",
  "workspace_member",
  "api_key",
  "user",
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
  "analytics",
  "achievement",
  "hero",
  "gamemode",
  "map",
  "division_grid",
  "log",
  "discord_channel",
  "challonge",
  "asset",
] as const;

type CrudResource = (typeof resourcesWithCrud)[number];
type CrudAction = "read" | "create" | "update" | "delete";
type CrudPermission = `${CrudResource}.${CrudAction}`;

type SpecialPermission =
  | "admin.*"
  | "role.read"
  | "role.create"
  | "role.update"
  | "role.delete"
  | "role.assign"
  | "permission.read"
  | "auth_user.read"
  | "auth_user.update"
  | "oauth_connection.read"
  | "oauth_connection.delete"
  | "auth_session.read"
  | "auth_session.revoke"
  | "team.import"
  | "team.export"
  | "player.import"
  | "player.export"
  | "match.sync"
  | "standing.recalculate"
  | "registration.approve"
  | "registration.reject"
  | "registration.check_in"
  | "registration_status.check_in"
  | "balancer.calculate"
  | "balancer.generate"
  | "balancer.publish"
  | "balancer.export"
  | "analytics.export"
  | "analytics.recalculate"
  | "achievement.calculate"
  | "achievement.import"
  | "achievement.export"
  | "hero.sync"
  | "gamemode.sync"
  | "map.sync"
  | "division_grid.import"
  | "division_grid.export"
  | "division_grid.publish"
  | "division_grid.sync"
  | "log.upload"
  | "log.stream"
  | "log.reprocess"
  | "discord_channel.sync"
  | "challonge.sync"
  | "asset.upload";

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
  workspaces: Array<{
    workspace_id: number;
    memberRole: string;
    permissions: string[];
  }>;
};

export function isAdminPanelRole(role: string): boolean {
  return role === "admin" || role === "tournament_organizer" || role === "moderator";
}

export function isWorkspaceAdminRole(role: string | undefined): boolean {
  return role === "owner";
}

function workspaceHasPermission(
  workspace: PermissionProfile["workspaces"][number] | undefined,
  permission: AppPermission,
): boolean {
  return workspace?.permissions.includes("admin.*") || workspace?.permissions.includes(permission) || false;
}

function permissionGrantsAdminPanelAccess(permission: string): boolean {
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
