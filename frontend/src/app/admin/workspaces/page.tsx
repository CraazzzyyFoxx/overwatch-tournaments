"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { PermissionGate } from "@/components/admin/PermissionGate";
import { WorkspacesBrowser } from "@/components/admin/workspaces/WorkspacesBrowser";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { usePermissions } from "@/hooks/usePermissions";

export default function WorkspacesPage() {
  const t = useTranslations("adminAccess.common");
  const tw = useTranslations("adminAccess.workspace");
  const { canManageAnyWorkspace, canUseCapability, isLoaded } = usePermissions();

  // The same gate `admin-navigation.ts` puts on `/admin/workspaces`: the row
  // carries no permission, only `workspaceAdminVisible`, which for a null
  // workspace scope is exactly "administers at least one workspace".
  return (
    <PermissionGate
      loaded={isLoaded}
      allowed={canManageAnyWorkspace()}
      description={tw("unauthorizedDescription")}
    >
      <div className="space-y-4">
        <AdminPageHeader
          title={t("workspaces")}
          actions={
            /* Creating a workspace is open to any active account now (the backend
               caps how many one account may own), so this is no longer a
               superuser button — but the right is revocable per account through
               negative RBAC, and the backend refuses a denied one, so the button
               goes away with it rather than offering a guaranteed 403. */
            canUseCapability("workspace.self_create") ? (
              <Button asChild size="sm">
                <Link href="/admin/workspaces/new">
                  <Plus className="size-3.5" aria-hidden />
                  {t("createWorkspace")}
                </Link>
              </Button>
            ) : null
          }
        />
        <WorkspacesBrowser />
      </div>
    </PermissionGate>
  );
}
