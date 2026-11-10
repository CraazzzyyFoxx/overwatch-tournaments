"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  WorkspaceNotListedNotice,
  WorkspaceVerificationIcon
} from "@/components/admin/workspace-verification";
import { WorkspaceIcon } from "@/components/admin/workspaces/WorkspaceCells";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { SetupChecklist } from "./SetupChecklist";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

/**
 * The root of both settings shells: which workspace this is, and what it still
 * lacks. Read-only, so no save bar; every "Set up" link leads into the section
 * that fixes the item.
 */
export function OverviewSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings");
  const settings = useWorkspaceSettingsForm(workspaceId, "overview");
  const pathname = usePathname();
  const basePath = pathname.startsWith("/admin/workspaces/")
    ? `/admin/workspaces/${workspaceId}`
    : "/admin/settings";

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ workspace }) => (
        <>
          <WorkspaceNotListedNotice status={workspace.verification_status} />

          <SettingsGrid>
            <SettingGroup id="workspace" title={t("overview.identity")}>
              <SettingRow label={t("overview.name")}>
                <span className="flex min-w-0 items-center gap-2">
                  <WorkspaceIcon workspace={workspace} />
                  <span className="truncate text-body font-medium">{workspace.name}</span>
                  <WorkspaceVerificationIcon status={workspace.verification_status} />
                </span>
              </SettingRow>
              <SettingRow label={t("overview.address")}>
                <span className="break-all font-mono text-body text-foreground">
                  {`${PLATFORM_ZONE}/workspace/${workspace.slug}`}
                </span>
              </SettingRow>
            </SettingGroup>

            <SettingGroup id="setup" title={t("setup.title")}>
              <SetupChecklist workspace={workspace} basePath={basePath} />
            </SettingGroup>
          </SettingsGrid>
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}
