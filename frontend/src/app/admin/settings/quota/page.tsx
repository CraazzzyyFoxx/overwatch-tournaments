"use client";

import { WorkspaceQuotaCard } from "@/components/admin/quota/WorkspaceQuotaCard";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Rate limits of the workspace this admin is working in.
 *
 * Gated on `workspace.update`, the permission behind `workspaces.quota_set`: a
 * workspace admin may only lower a number here, and the server is what enforces
 * that — raising one answers 422 and the offending field says so.
 */
export default function WorkspaceQuotaSettingsPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace in the sidebar to see and edit its rate limits."
      />
    );
  }

  if (!canAccessPermission("workspace.update", workspaceId)) {
    return (
      <PageStateCard
        state="not-found"
        title="Not available"
        description="Editing rate limits needs the workspace.update permission in this workspace."
      />
    );
  }

  return <WorkspaceQuotaCard workspaceId={workspaceId} />;
}
