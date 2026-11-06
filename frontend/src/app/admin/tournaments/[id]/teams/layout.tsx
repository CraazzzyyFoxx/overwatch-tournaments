"use client";

import { useEffect, type ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import type { LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";

import { useHubTournamentQuery } from "../hubQueries";
import { SubTabShell, useSubTabSegment, useTabAccess } from "../sub-tabs";
import { allowedTeamsSubTab, TEAMS_SUB_TABS, type TeamsSubTab } from "../tab-guards";

const DEFAULT_SUB_TAB: TeamsSubTab = TEAMS_SUB_TABS[0];

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
  const router = useRouter();
  const { isLoaded: permissionsLoaded } = usePermissions();
  const t = useTranslations("adminTournament.teams");

  const basePath = `/admin/tournaments/${tournamentId}/teams`;
  const { active } = useSubTabSegment(basePath, TEAMS_SUB_TABS, DEFAULT_SUB_TAB);

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const access = useTabAccess(tournamentQuery.data);
  const activeAllowed = allowedTeamsSubTab(active, access);

  // Decided only once the tournament is in: its formation nodes are unknown while
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
    label: t(`tabs.${key}`),
    href: `${basePath}/${key}`,
    hidden: !allowedTeamsSubTab(key, access)
  }));

  return (
    <SubTabShell items={items} activeKey={active} ariaLabel={t("ariaLabel")} allowed={activeAllowed}>
      {children}
    </SubTabShell>
  );
}
