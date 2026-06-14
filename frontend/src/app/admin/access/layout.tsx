"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  accessApiKeysPermissions,
  accessPermissionsPermissions,
  accessRolesPermissions,
  accessUsersPermissions,
} from "@/components/admin/admin-navigation";
import { cn } from "@/lib/utils";
import { type AppPermission, usePermissions } from "@/hooks/usePermissions";

type AccessNavItem = {
  href: string;
  label: string;
  permissions: AppPermission[];
  superuserOnly?: boolean;
  workspaceAdminVisible?: boolean;
};

const accessNavItems: AccessNavItem[] = [
  { href: "/admin/access/users", label: "Users", permissions: accessUsersPermissions },
  { href: "/admin/access/roles", label: "Roles", permissions: accessRolesPermissions },
  { href: "/admin/access/permissions", label: "Permissions", permissions: accessPermissionsPermissions },
  { href: "/admin/access/oauth", label: "OAuth Connections", permissions: accessUsersPermissions },
  {
    href: "/admin/access/api-keys",
    label: "API Keys",
    permissions: accessApiKeysPermissions,
    workspaceAdminVisible: true,
  },
  { href: "/admin/access/sessions", label: "Sessions", permissions: [], superuserOnly: true },
];

export default function AccessAdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isSuperuser, hasAnyPermission, hasAnyWorkspacePermission, canManageAnyWorkspace } = usePermissions();
  const visibleNavItems = accessNavItems.filter((item) => {
    if (item.superuserOnly) {
      return isSuperuser;
    }

    if (item.workspaceAdminVisible) {
      return isSuperuser || hasAnyWorkspacePermission(item.permissions) || canManageAnyWorkspace();
    }

    return isSuperuser || hasAnyPermission(item.permissions);
  });

  if (visibleNavItems.length === 0) {
    return null;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2 rounded-lg border border-border/60 bg-card/60 p-2">
        {visibleNavItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                isActive && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
      {children}
    </div>
  );
}
