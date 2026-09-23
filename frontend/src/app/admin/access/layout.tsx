"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTabs, type AdminTabItem } from "@/components/kit/AdminTabs";
import { PageStateCard } from "@/components/ui/page-state-card";
import {
  accessApiKeysPermissions,
  accessPermissionsPermissions,
  accessRolesPermissions,
  accessUsersPermissions
} from "@/lib/auth/admin-permissions";
import { type AppPermission, usePermissions } from "@/hooks/usePermissions";

/**
 * The six Access sections and the gate each one keeps.
 *
 * These MUST agree with `adminRoutePermissions` in `admin-navigation.ts` —
 * that table guards the route, this one hides the tab, and a tab visible to
 * someone the route rejects is a dead end. Accounts, OAuth and Permissions are
 * global-only reads; Roles and API keys are also visible to a workspace admin;
 * Sessions is superuser-only.
 */
const ACCESS_TABS: {
  key: string;
  label: string;
  permissions: AppPermission[];
  workspaceAdminVisible?: boolean;
  superuserOnly?: boolean;
}[] = [
  { key: "accounts", label: "Accounts", permissions: accessUsersPermissions },
  {
    key: "roles",
    label: "Roles",
    permissions: accessRolesPermissions,
    workspaceAdminVisible: true
  },
  { key: "permissions", label: "Permissions", permissions: accessPermissionsPermissions },
  {
    key: "api-keys",
    label: "API keys",
    permissions: accessApiKeysPermissions,
    workspaceAdminVisible: true
  },
  { key: "oauth", label: "OAuth", permissions: accessUsersPermissions },
  { key: "sessions", label: "Sessions", permissions: [], superuserOnly: true }
];

/**
 * Access (F15): navigation and chrome only.
 *
 * The hand-rolled pill `<nav>` this replaces was the last bespoke tab bar in
 * the admin panel; it is now the same `AdminTabs` every other hub uses, so a
 * section reads as a tab whether you arrive from the sidebar, the command
 * palette or a link.
 */
export default function AccessAdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const { isSuperuser, hasAnyPermission, hasAnyWorkspacePermission, canManageAnyWorkspace } =
    usePermissions();

  const items: AdminTabItem[] = ACCESS_TABS.map((tab) => {
    const visible = tab.superuserOnly
      ? isSuperuser
      : isSuperuser ||
        hasAnyPermission(tab.permissions) ||
        (tab.workspaceAdminVisible === true &&
          (hasAnyWorkspacePermission(tab.permissions) || canManageAnyWorkspace()));

    return {
      key: tab.key,
      label: tab.label,
      href: `/admin/access/${tab.key}`,
      hidden: !visible
    };
  });

  const activeKey =
    ACCESS_TABS.find((tab) => pathname.startsWith(`/admin/access/${tab.key}`))?.key ?? "";

  return (
    <div className="space-y-4">
      <AdminPageHeader
        title="Access"
        description="Staff accounts, roles, permissions, API keys, OAuth connections and sessions."
      />
      <AdminTabs items={items} activeKey={activeKey} level={1} ariaLabel="Access sections" />
      {items.every((item) => item.hidden) ? (
        <PageStateCard
          state="empty"
          title="No Access section is open to you"
          description="Reading accounts, roles or permissions needs a global RBAC grant; API keys need workspace admin."
        />
      ) : (
        children
      )}
    </div>
  );
}
