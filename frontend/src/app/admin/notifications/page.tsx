"use client";

import { useTranslations } from "next-intl";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { PermissionGate } from "@/components/admin/PermissionGate";
import { NotificationsBrowser } from "@/components/admin/notifications/NotificationsBrowser";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

export default function AdminWorkspaceNotificationsPage() {
  const { canAccessPermission, isLoaded } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const t = useTranslations<never>();

  // No workspace picked is not a missing grant: there is nothing to ask for yet.
  return (
    <PermissionGate
      loaded={isLoaded}
      allowed={workspaceId == null || canAccessPermission("notification.read", workspaceId)}
      description={t("notifications.workspaceAdmin.unauthorized.description")}
    >
      {workspaceId == null ? (
        <div className="space-y-4">
          <AdminPageHeader
            title={t("notifications.workspaceAdmin.title")}
            description={t("notifications.workspaceAdmin.description")}
          />
          <EmptyNote className="text-center">
            {t("notifications.workspaceAdmin.pickWorkspace")}
          </EmptyNote>
        </div>
      ) : (
        <NotificationsBrowser
          workspaceId={workspaceId}
          // Two grants, two questions — the server checks them separately, so a
          // `notification.read` holder gets the table with no retire control at all.
          canRetire={canAccessPermission("notification.delete", workspaceId)}
        />
      )}
    </PermissionGate>
  );
}
