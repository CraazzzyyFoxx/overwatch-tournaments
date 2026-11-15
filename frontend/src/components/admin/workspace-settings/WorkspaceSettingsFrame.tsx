"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Card, CardContent } from "@craazzzyyfoxx/admin-kit/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import type { Workspace } from "@/types/workspace.types";
import type { WorkspaceSettingsFormState } from "./fields";
import type { WorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

interface WorkspaceSettingsFrameContext {
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
  const t = useTranslations("adminWorkspace.workspaceSettings.frame");
  const { isLoaded, isSuperuser, isWorkspaceAdmin } = usePermissions();

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title={t("noSelectedTitle")}
        description={t("noSelectedDescription")}
      />
    );
  }

  if (!isLoaded || settings.isLoading) {
    // Form-shaped: label + control rows in the section card, so nothing
    // reflows when the record lands.
    return (
      <Card aria-busy="true">
        <CardContent className="flex flex-col gap-5 pt-6">
          <span className="sr-only">{t("loading")}</span>
          {[0, 1, 2].map((row) => (
            <div key={row} className="flex flex-col gap-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  if (!(isSuperuser || isWorkspaceAdmin(workspaceId))) {
    return (
      <PageStateCard
        state="error"
        title={t("notYourTitle")}
        description={t("notYourDescription")}
      />
    );
  }

  if (settings.isError) {
    return (
      <PageStateCard state="error" title={t("loadErrorTitle")} onAction={settings.refetch} />
    );
  }

  if (!settings.workspace || !settings.form) {
    return (
      <PageStateCard
        state="not-found"
        title={t("notFoundTitle")}
        description={t("notFoundDescription")}
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
