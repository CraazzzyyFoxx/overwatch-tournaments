"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { PermissionGate } from "@/components/admin/PermissionGate";
import { AuditBrowser } from "@/components/admin/audit/AuditBrowser";
import { ALL_WORKSPACES, LEGACY_ALL_WORKSPACES, SCOPE_PARAM } from "@/components/admin/audit/model";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useWorkspaceStore } from "@/stores/workspace.store";

export default function AdminAuditPage() {
  const t = useTranslations("adminMatches.audit");
  const { isSuperuser, canAccessPermission, isLoaded } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const scope = searchParams?.get(SCOPE_PARAM) ?? null;
  // An old `?scope=all` link still opens the platform-wide feed, and is
  // rewritten to the toggle chip's `1` so the chip shows it as on.
  useEffect(() => {
    if (scope === LEGACY_ALL_WORKSPACES) setParams({ [SCOPE_PARAM]: ALL_WORKSPACES });
  }, [scope, setParams]);
  // A superuser with no workspace picked has no narrower scope to fall back to,
  // so the feed IS platform-wide, and the empty state must not claim a
  // workspace it is not filtering by. Read off the scope chip's own param: the
  // gate below needs it before the chips exist.
  const allWorkspaces =
    isSuperuser &&
    (scope === ALL_WORKSPACES || scope === LEGACY_ALL_WORKSPACES || workspaceId == null);

  // A non-superuser request without a workspace is a 422, not a wider feed, so
  // there is nothing to ask for until one is picked — and "no access" would be
  // the wrong thing to say to someone who has simply picked nothing: without a
  // scope there is no scope to hold a grant in.
  const needsScope = !isSuperuser && workspaceId == null;

  // The same grant `AuditTrailButton` asks for, in the scope this feed queries.
  // The server requires `audit.read` in the requested workspace, so without it
  // every request on this screen is a 403 — saying so once beats a table of them.
  return (
    <PermissionGate
      loaded={isLoaded}
      allowed={needsScope || canAccessPermission("audit.read", allWorkspaces ? null : workspaceId)}
      description={t("noPermission")}
    >
      <div className="space-y-4">
        <AdminPageHeader title={t("title")} description={t("readOnlyDescription")} />
        {needsScope ? (
          <EmptyNote className="text-center">{t("scopeDescription")}</EmptyNote>
        ) : (
          <AuditBrowser
            workspaceId={workspaceId}
            allWorkspaces={allWorkspaces}
            isSuperuser={isSuperuser}
          />
        )}
      </div>
    </PermissionGate>
  );
}
