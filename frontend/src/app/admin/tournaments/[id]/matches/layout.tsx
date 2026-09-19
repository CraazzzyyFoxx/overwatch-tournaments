"use client";

import type { ReactNode } from "react";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { AdminTabs, type AdminTabItem } from "@/components/kit/AdminTabs";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament-workspace-query-keys";
import { useHubTournamentQuery } from "../hubQueries";
import { MATCHES_SUB_TABS, type MatchesSubTabKey } from "../tab-guards";

const SUB_TAB_LABELS: Record<MatchesSubTabKey, string> = {
  encounters: "Encounters",
  standings: "Standings",
  reports: "Reports",
  parsed: "Parsed maps",
  logs: "Logs"
};

/**
 * Scope params the five views share. Carried across a tab switch so narrowing
 * to a stage survives moving from Encounters to Standings beside it (F8 ·2);
 * everything else — `id`, `page`, `search`, and the per-view chips — is left
 * behind, because a row id or a status means something different in each view.
 */
const SHARED_SCOPE_PARAMS = ["stage", "group"] as const;

/**
 * Sub-tab bar of the Matches hub tab. Navigation and queue badges, nothing
 * else: the views own their own data, and realtime is mounted once in
 * `TournamentHubShell`.
 *
 * The badge queries address the same keys their views do, so mounting this bar
 * costs no extra request — TanStack dedupes the observers.
 */
export default function MatchesLayout({ children }: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { canAccessPermission } = usePermissions();

  const basePath = `/admin/tournaments/${tournamentId}/matches`;
  const segment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? MATCHES_SUB_TABS[0])
    : MATCHES_SUB_TABS[0];

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const workspaceId = tournamentQuery.data?.workspace_id ?? null;
  const canReadMatch = canAccessPermission("match.read", workspaceId);

  const reportStatsQuery = useQuery({
    queryKey: [
      "encounter-reports",
      "stats",
      { workspace_id: workspaceId, tournament_id: tournamentId }
    ],
    queryFn: () =>
      adminService.getEncounterReportStats({
        workspace_id: workspaceId!,
        tournament_id: tournamentId
      }),
    enabled: canReadMatch && workspaceId != null
  });

  const logStatsQuery = useQuery({
    queryKey: [...getTournamentWorkspaceQueryKeys(tournamentId).logHistory, "stats"],
    queryFn: () => adminService.getLogStats(tournamentId),
    enabled: canReadMatch
  });

  const scope = new URLSearchParams();
  for (const key of SHARED_SCOPE_PARAMS) {
    const value = searchParams.get(key);
    if (value) scope.set(key, value);
  }
  const scopeQuery = scope.toString();

  const disputed = reportStatsQuery.data?.by_result_status.disputed ?? 0;
  const logQueue = logStatsQuery.data
    ? logStatsQuery.data.pending + logStatsQuery.data.processing
    : 0;

  const items: AdminTabItem[] = MATCHES_SUB_TABS.map((key) => ({
    key,
    label: SUB_TAB_LABELS[key],
    href: scopeQuery ? `${basePath}/${key}?${scopeQuery}` : `${basePath}/${key}`,
    badge:
      key === "reports"
        ? disputed || undefined
        : key === "logs"
          ? logQueue || undefined
          : undefined
  }));

  return (
    <div className="space-y-4">
      <AdminTabs items={items} activeKey={segment} level={2} ariaLabel="Matches views" />
      {children}
    </div>
  );
}
