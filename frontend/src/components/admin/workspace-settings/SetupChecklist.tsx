"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { CircleCheck, CircleDashed } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TONE_TEXT } from "@/components/ui/tone";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { cn } from "@/lib/utils";
import { workspaceSetupChecklist } from "@/lib/workspace/setup-checklist";
import type { Workspace } from "@/types/workspace.types";

/**
 * The setup checklist of one workspace, as rows: a glyph for done/not yet,
 * the item, and for what is not done yet one sentence on what it gives and a
 * link into the section that sets it.
 *
 * Rendered by the wizard's last step and by the settings overview from the
 * same `workspaceSetupChecklist`, so the two never disagree on what counts
 * as set up. `basePath` is the shell's prefix (`/admin/settings` or
 * `/admin/workspaces/8`), because the same workspace is reached through both.
 *
 * Unframed, rows flush with the edge: the overview puts it inside a settings
 * group card, and a frame of its own there would be a frame in a frame
 * (DESIGN §5). A host without a surface frames it.
 */
export function SetupChecklist({
  workspace,
  basePath
}: Readonly<{ workspace: Workspace; basePath: string }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.setup");
  const items = workspaceSetupChecklist(workspace);

  return (
    <ul aria-label={t("title")} className="divide-y divide-[color:var(--aqt-border)]">
      {items.map((item) => {
        const Glyph = item.done ? CircleCheck : CircleDashed;
        return (
          <li key={item.key} className="flex items-center gap-2.5 py-3 first:pt-0 last:pb-0">
            <Glyph
              aria-hidden
              className={cn("mt-0.5 size-4 shrink-0 self-start", item.done ? TONE_TEXT.success : TONE_TEXT.neutral)}
            />
            <span className="sr-only">{item.done ? t("done") : t("todo")}</span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <p className="text-sm font-medium">{t(`items.${item.key}`)}</p>
              {item.done ? null : (
                <p className="text-caption text-[color:var(--aqt-fg-muted)]">
                  {t(`hints.${item.key}`, { zone: PLATFORM_ZONE })}
                </p>
              )}
            </div>
            {!item.done && item.section ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`${basePath}/${item.section}${item.group ? `#${item.group}` : ""}`}>{t("setUp")}</Link>
              </Button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
