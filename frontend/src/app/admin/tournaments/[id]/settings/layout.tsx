"use client";

import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AdminSectionNav, type AdminSectionNavGroup } from "@/components/kit/AdminSectionNav";
import { usePermissions } from "@/hooks/usePermissions";
import { useHubTournamentQuery } from "../hubQueries";
import { allowedSettingsSection, SETTINGS_SECTIONS, type TabAccess } from "../tab-guards";
import { SETTINGS_SECTION_GROUPS, SETTINGS_SECTION_LABELS } from "./settings-sections";

/**
 * Navigation of the settings hub (T5) — and nothing else.
 *
 * No queries and no subscriptions live here: the hub shell is the single
 * realtime mount, and the tournament read below is the same cached key the
 * shell already resolved (TanStack dedupes the observer), needed only to
 * decide which sections this caller may open.
 */
export default function TournamentSettingsLayout({
  children
}: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  // `/admin/tournaments/14/settings/pre-game` → section `pre-game`.
  const sectionSegment = usePathname().split("/").filter(Boolean).at(-1) ?? "";
  const activeKey = (SETTINGS_SECTIONS as readonly string[]).includes(sectionSegment)
    ? sectionSegment
    : "";

  const { canAccessPermission } = usePermissions();
  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const workspaceId = tournamentQuery.data?.workspace_id ?? null;

  const access: TabAccess = {
    canUpdateTournament: canAccessPermission("tournament.update", workspaceId),
    canUpdateEncounter: canAccessPermission("match.update", workspaceId),
    canTeamRead: canAccessPermission("team.read", workspaceId),
    canTeamCreate: canAccessPermission("team.create", workspaceId),
    canReadTournamentLink: canAccessPermission("tournament_link.read", workspaceId),
    canDeleteTournament: canAccessPermission("tournament.delete", workspaceId),
    teamFormation: tournamentQuery.data?.team_formation === "draft" ? "draft" : "balancer"
  };

  const groups: AdminSectionNavGroup[] = SETTINGS_SECTION_GROUPS.map((group) => ({
    label: group.label,
    items: group.sections.map((section) => ({
      key: section,
      label: SETTINGS_SECTION_LABELS[section],
      href: `/admin/tournaments/${tournamentId}/settings/${section}`,
      tone: section === "danger" ? ("danger" as const) : undefined,
      hidden: !allowedSettingsSection(section, access)
    }))
  }));

  return (
    <div className="flex flex-col gap-4 md:flex-row md:gap-6">
      <AdminSectionNav groups={groups} activeKey={activeKey} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
