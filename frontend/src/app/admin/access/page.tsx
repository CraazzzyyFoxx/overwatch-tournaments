"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import {
  accessApiKeysPermissions,
  accessPermissionsPermissions,
  accessRolesPermissions,
  accessUsersPermissions,
} from "@/components/admin/admin-navigation";
import { type AppPermission, usePermissions } from "@/hooks/usePermissions";

type AccessRoute = {
  href: string;
  permissions: AppPermission[];
  workspaceAdminVisible?: boolean;
};

const accessRoutes: AccessRoute[] = [
  { href: "/admin/access/users", permissions: accessUsersPermissions },
  { href: "/admin/access/roles", permissions: accessRolesPermissions },
  { href: "/admin/access/permissions", permissions: accessPermissionsPermissions },
  { href: "/admin/access/api-keys", permissions: accessApiKeysPermissions, workspaceAdminVisible: true },
];

export default function AccessAdminIndexPage() {
  const router = useRouter();
  const { isLoaded, isSuperuser, hasAnyPermission, hasAnyWorkspacePermission, canManageAnyWorkspace } = usePermissions();

  useEffect(() => {
    if (!isLoaded) {
      return;
    }

    const firstAccessibleRoute = accessRoutes.find(
      (route) =>
        isSuperuser ||
        hasAnyPermission(route.permissions) ||
        (route.workspaceAdminVisible && (hasAnyWorkspacePermission(route.permissions) || canManageAnyWorkspace())),
    );

    if (firstAccessibleRoute) {
      router.replace(firstAccessibleRoute.href);
    }
  }, [canManageAnyWorkspace, hasAnyPermission, hasAnyWorkspacePermission, isLoaded, isSuperuser, router]);

  return null;
}
