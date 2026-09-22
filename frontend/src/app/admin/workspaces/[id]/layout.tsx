import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { WORKSPACE_RECORD_SECTIONS } from "@/components/admin/workspace-settings/sections";
import { WorkspaceSettingsShell } from "@/components/admin/workspace-settings/WorkspaceSettingsShell";

/**
 * The same settings hub, scoped to a workspace named in the route: a superuser
 * editing someone else's workspace rather than their own.
 *
 * The rail is narrowed to the sections that exist under both shells. Divisions,
 * statuses, sub-roles and subscriptions are workspace-scoped screens of their
 * own and route only under `/admin/settings`, so listing them here would be a
 * 404 dressed up as navigation.
 */
export default async function WorkspaceScopedSettingsLayout({
  params,
  children
}: Readonly<{ params: Promise<{ id: string }>; children: ReactNode }>) {
  const { id } = await params;

  return (
    <WorkspaceSettingsShell
      basePath={`/admin/workspaces/${id}`}
      sections={WORKSPACE_RECORD_SECTIONS}
      actions={
        <Button asChild variant="ghost" size="sm">
          <Link href="/admin/workspaces">
            <ArrowLeft aria-hidden className="mr-2 size-4" /> All workspaces
          </Link>
        </Button>
      }
    >
      {children}
    </WorkspaceSettingsShell>
  );
}
