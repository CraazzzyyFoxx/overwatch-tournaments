"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";

import { SetupChecklist } from "@/components/admin/workspace-settings/SetupChecklist";
import { WorkspaceIcon } from "@/components/admin/workspaces/WorkspaceCells";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { RowButton } from "@/components/ui/row-button";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

const NEXT_LINKS = [
  { key: "tournament", href: "/admin/tournaments?create=1" },
  { key: "members", href: "/admin/members" },
  { key: "access", href: "/admin/access" }
] as const;

/**
 * Step 5: the workspace as it now stands, what is left to set up, and where
 * to go next. Arriving here makes it the admin's current workspace, so every
 * link below (settings, members, access) lands in it.
 */
export function DoneStep({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = useTranslations("adminWorkspace.newWorkspace.done");
  const setCurrentWorkspace = useWorkspaceStore((state) => state.setCurrentWorkspace);

  useEffect(() => {
    setCurrentWorkspace(workspace.id);
  }, [setCurrentWorkspace, workspace.id]);

  return (
    <div className="flex flex-col gap-6">
      <Card className="flex items-center gap-2.5 px-4 py-3">
        <WorkspaceIcon workspace={workspace} />
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-sm font-medium">{workspace.name}</p>
          <p className="truncate font-mono text-caption text-[color:var(--aqt-fg-muted)]">
            {PLATFORM_ZONE}/workspace/{workspace.slug}
          </p>
        </div>
      </Card>

      <section className="flex flex-col gap-2">
        <h3 className={eyebrowClass("muted")}>{t("setupTitle")}</h3>
        <Card className="px-4 py-3">
          <SetupChecklist workspace={workspace} basePath="/admin/settings" />
        </Card>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className={eyebrowClass("muted")}>{t("nextTitle")}</h3>
        <Card asChild className="divide-y divide-[color:var(--aqt-border)] overflow-hidden">
          <ul>
            {NEXT_LINKS.map(({ key, href }) => (
              <li key={key}>
                <RowButton asChild className="flex items-center gap-2.5 px-4 py-3">
                  <Link href={href}>
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="text-sm font-medium">{t(`next.${key}.title`)}</span>
                      <span className="text-caption text-[color:var(--aqt-fg-muted)]">
                        {t(`next.${key}.description`)}
                      </span>
                    </span>
                    <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  </Link>
                </RowButton>
              </li>
            ))}
          </ul>
        </Card>
      </section>
    </div>
  );
}
