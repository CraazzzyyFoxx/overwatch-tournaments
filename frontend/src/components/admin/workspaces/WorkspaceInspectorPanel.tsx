"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { InspectorField } from "@/components/kit/InspectorField";
import { WorkspaceOwnerValue } from "@/components/admin/workspace-owner";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import type { WorkspaceListItem } from "@/types/workspace.types";

/**
 * The open workspace's settings at a glance; changing any of them happens
 * under `[id]/`. Active/listed are in the row's icon columns, so they are not
 * repeated here; unset values and defaults render no field.
 */
export function WorkspaceInspectorPanel({ workspace }: Readonly<{ workspace: WorkspaceListItem }>) {
  const t = useTranslations("adminAccess.common");
  const tw = useTranslations("adminAccess.workspace");

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <InspectorField label={t("timezone")}>{workspace.timezone}</InspectorField>
        <InspectorField label={t("branding")}>
          {workspace.branding_enabled ? t("customBranding") : null}
        </InspectorField>
        <InspectorField label={t("subdomain")}>{workspace.subdomain}</InspectorField>
        <InspectorField label={t("customDomain")}>
          {workspace.custom_domain
            ? workspace.custom_domain_verified_at
              ? workspace.custom_domain
              : tw("unverifiedDomain", { domain: workspace.custom_domain })
            : null}
        </InspectorField>
        <InspectorField label={t("discordGuild")}>{workspace.discord_guild_id}</InspectorField>
        <InspectorField label={t("newcomers")}>
          {workspace.newcomer_scope === "global" ? t("anyWorkspace") : t("thisWorkspace")}
        </InspectorField>
        <InspectorField label={t("owner")}>
          <WorkspaceOwnerValue workspaceId={workspace.id} />
        </InspectorField>
      </div>

      <InspectorField label={t("description")}>{workspace.description}</InspectorField>
    </div>
  );
}

/** The header actions of the same row: edit goes to the settings sections, delete stays here. */
export function WorkspaceInspectorActions({
  workspace,
  canEdit,
  canDelete,
  onDelete
}: Readonly<{
  workspace: WorkspaceListItem;
  canEdit: boolean;
  canDelete: boolean;
  onDelete: (workspace: WorkspaceListItem) => void;
}>) {
  const t = useTranslations("adminAccess.common");

  return (
    <>
      {canEdit ? (
        <Button asChild variant="outline" size="sm">
          <Link href={`/admin/workspaces/${workspace.id}/general`}>{t("edit")}</Link>
        </Button>
      ) : null}
      {canDelete ? (
        <Button
          variant="outline"
          size="sm"
          className="text-danger"
          onClick={() => onDelete(workspace)}
        >
          {t("delete")}
        </Button>
      ) : null}
    </>
  );
}
