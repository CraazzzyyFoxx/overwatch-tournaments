"use client";

import type { ReactNode } from "react";

import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import type { Workspace } from "@/types/workspace.types";
import { Spinner } from "@/components/ui/spinner";
import type { WorkspaceSettingsFormState } from "./fields";
import type { WorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

export interface WorkspaceSettingsFrameContext {
  workspace: Workspace;
  workspaceId: number;
  form: WorkspaceSettingsFormState;
}

export interface WorkspaceSettingsFrameProps {
  workspaceId: number | null;
  settings: WorkspaceSettingsForm;
  /** JSX only — every hook a section needs belongs in the section body, above
   * this frame, or it becomes a conditional hook. */
  children: (context: WorkspaceSettingsFrameContext) => ReactNode;
}

/**
 * The permission gate and the load states of one workspace settings section.
 *
 * The gate lives here rather than in the rail because hiding a link is not
 * access control: `/admin/workspaces/8/branding` typed into the address bar
 * has to be refused too, and refusing it in five copies is how one of them
 * ends up missing.
 */
export function WorkspaceSettingsFrame({
  workspaceId,
  settings,
  children
}: Readonly<WorkspaceSettingsFrameProps>) {
  const { isLoaded, isSuperuser, isWorkspaceAdmin } = usePermissions();

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace in the header to edit its settings."
      />
    );
  }

  if (!isLoaded || settings.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Spinner className="mr-2 size-5" /> Loading workspace…
      </div>
    );
  }

  if (!(isSuperuser || isWorkspaceAdmin(workspaceId))) {
    return (
      <PageStateCard
        state="error"
        title="Not your workspace"
        description="You don't have permission to manage this workspace's settings."
      />
    );
  }

  if (settings.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load the workspace"
        description="The workspace record failed to load. Retry, or reload the page."
      />
    );
  }

  if (!settings.workspace || !settings.form) {
    return (
      <PageStateCard
        state="not-found"
        title="Workspace not found"
        description="This workspace no longer exists, or you cannot see it."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {children({
        workspace: settings.workspace,
        workspaceId,
        form: settings.form
      })}
    </div>
  );
}
