"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { SectionNav } from "@/components/kit/SectionNav";
import {
  WORKSPACE_SETTINGS_SECTIONS,
  WORKSPACE_SETTINGS_SECTION_DESCRIPTIONS,
  WORKSPACE_SETTINGS_SECTION_LABELS,
  workspaceSettingsNavGroups,
  type WorkspaceSettingsSectionKey
} from "./sections";

export interface WorkspaceSettingsShellProps {
  /** Route prefix the rail links against: `/admin/settings` or `/admin/workspaces/8`. */
  basePath: string;
  /** Sections this shell routes; the rest are hidden from the rail. */
  sections?: readonly WorkspaceSettingsSectionKey[];
  /** Rendered to the right of the heading (a back link, an audit trail). */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Screens under the hub that render without the hub's chrome.
 *
 * A child `layout.tsx` cannot remove a parent one — Next.js nests them — so
 * the division-grid editor's own full-screen layout would still sit inside
 * this header and rail, making its three columns a fourth column short of the
 * viewport (the layout IA §9 rejects). The opt-out therefore has to live where
 * the chrome is rendered, not where it is unwanted.
 */
const FULL_SCREEN_PREFIXES = ["/admin/settings/divisions/v/"] as const;

/**
 * Chrome of the workspace settings hub (T5): the heading, the section rail and
 * nothing else.
 *
 * Both shells mount this one — `/admin/settings` for the workspace an admin is
 * in, `/admin/workspaces/[id]` for a superuser looking at another — so a
 * section page is only its own form, and neither shell can drift into a second
 * heading or a second rail.
 *
 * The active section is resolved from the first path segment after `basePath`,
 * not the last segment of the URL: `/admin/settings/divisions/import` is a
 * child screen of Divisions and has to leave that rail item current.
 */

export function WorkspaceSettingsShell({
  basePath,
  sections,
  actions,
  children
}: Readonly<WorkspaceSettingsShellProps>) {
  const pathname = usePathname();
  if (FULL_SCREEN_PREFIXES.some((prefix) => pathname.startsWith(prefix))) return <>{children}</>;

  const trailing = pathname.startsWith(basePath) ? pathname.slice(basePath.length) : "";
  const segment = trailing.split("/").filter(Boolean)[0] ?? "";
  const activeKey = (WORKSPACE_SETTINGS_SECTIONS as readonly string[]).includes(segment)
    ? (segment as WorkspaceSettingsSectionKey)
    : null;

  return (
    <div className="flex flex-col gap-4">
      <AdminPageHeader
        title={activeKey ? WORKSPACE_SETTINGS_SECTION_LABELS[activeKey] : "Workspace settings"}
        description={
          activeKey ? WORKSPACE_SETTINGS_SECTION_DESCRIPTIONS[activeKey] : undefined
        }
        actions={actions}
      />
      <div className="flex flex-col gap-4 md:flex-row md:gap-6">
        <SectionNav
          groups={workspaceSettingsNavGroups(basePath, sections)}
          activeKey={activeKey ?? ""}
        />
        {/* Not `<main>`: the admin shell already exposes the page-level main
            landmark (`components/ui/sidebar.tsx` SidebarInset). */}
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
