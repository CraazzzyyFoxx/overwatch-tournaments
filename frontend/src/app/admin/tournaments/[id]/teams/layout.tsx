"use client";

import { useEffect, type ReactNode } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";

import { useHubTournamentQuery } from "../hubQueries";
import { allowedTeamsSubTab, TEAMS_SUB_TABS, type TabAccess, type TeamsSubTab } from "../tab-guards";

const SUB_TAB_LABELS: Record<TeamsSubTab, string> = {
  roster: "Roster",
  draft: "Draft"
};

const DEFAULT_SUB_TAB: TeamsSubTab = TEAMS_SUB_TABS[0];

function isTeamsSubTab(value: string): value is TeamsSubTab {
  return (TEAMS_SUB_TABS as readonly string[]).includes(value);
}

/**
 * Sub-tab bar of the Teams hub tab (§5 P2-4): Roster · Draft.
 *
 * Navigation only — the hub shell owns the realtime mount, the header and the
 * permission gate; every query here is a read of a key the shell already holds.
 * `Draft` is not a permission but a tournament property: a balancer tournament
 * has no draft, so the tab is hidden AND the route bounces to Roster, the same
 * pair the hub guard uses (a hidden-but-reachable tab is the bug this prevents).
 */
export default function TeamsLayout({ children }: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const pathname = usePathname();
  const router = useRouter();
  const { canAccessPermission, isLoaded: permissionsLoaded } = usePermissions();

  const basePath = `/admin/tournaments/${tournamentId}/teams`;
  const segment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? DEFAULT_SUB_TAB)
    : DEFAULT_SUB_TAB;
  const active: TeamsSubTab = isTeamsSubTab(segment) ? segment : DEFAULT_SUB_TAB;

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
  const activeAllowed = allowedTeamsSubTab(active, access);

  // Decided only once the tournament is in: `team_formation` is unknown while
  // it loads, and bouncing on that first paint would kick a legitimate draft
  // admin off their own tab.
  useEffect(() => {
    if (!permissionsLoaded || !tournamentQuery.data) return;
    if (!activeAllowed) {
      router.replace(`${basePath}/${DEFAULT_SUB_TAB}`);
    }
  }, [permissionsLoaded, tournamentQuery.data, activeAllowed, basePath, router]);

  const items: LinkTabItem[] = TEAMS_SUB_TABS.map((key) => ({
    key,
    label: SUB_TAB_LABELS[key],
    href: `${basePath}/${key}`,
    hidden: !allowedTeamsSubTab(key, access)
  }));

  return (
    <div className="space-y-4">
      <LinkTabs items={items} activeKey={active} level={2} ariaLabel="Teams sections" />
      {activeAllowed ? children : null}
    </div>
  );
}
