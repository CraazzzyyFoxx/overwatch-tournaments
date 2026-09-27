"use client";

import { useEffect, type ReactNode } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import { useHubStagesQuery, useHubTournamentQuery } from "../hubQueries";
import {
  allowedMatchesSubTab,
  MATCHES_SUB_TABS,
  type MatchesSubTabKey
} from "../tab-guards";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

const SUB_TAB_LABELS: Record<MatchesSubTabKey, string> = {
  encounters: "Encounters",
  lobbies: "Lobbies",
  standings: "Standings",
  reports: "Reports",
  parsed: "Parsed maps",
  logs: "Logs"
};

/**
 * Scope params the Matches views share. Carried across a tab switch so
 * narrowing to a stage survives moving from Encounters to Standings beside it
 * (F8 ·2); everything else — `id`, `page`, `search`, and the per-view chips —
 * is left behind, because a row id or a status means something different in
 * each view.
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
  const router = useRouter();
  const { canAccessPermission } = usePermissions();

  const basePath = `/admin/tournaments/${tournamentId}/matches`;
  const segment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? MATCHES_SUB_TABS[0])
    : MATCHES_SUB_TABS[0];

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const workspaceId = tournamentQuery.data?.workspace_id ?? null;
  const canReadMatch = canAccessPermission("match.read", workspaceId);

  // The Lobbies view exists only where there is a lobby: an FFA stage. The
  // stages are the hub's own query, so asking costs no extra request.
  const stagesQuery = useHubStagesQuery(tournamentId);
  const hasFfaStage = (stagesQuery.data ?? []).some((stage) =>
    FFA_STAGE_TYPES.includes(stage.stage_type)
  );

  const reportStatsQuery = useQuery({
    queryKey: encounterQueryKeys.reportStats({ workspace_id: workspaceId, tournament_id: tournamentId }),
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

  // Nothing is rendered under a view this tournament does not have, not even
  // for the paint before the bounce lands: `hasFfaStage` is false until the
  // stages are in, so the Lobbies page never mounts against a duel tournament.
  const activeAllowed =
    !(MATCHES_SUB_TABS as readonly string[]).includes(segment) ||
    allowedMatchesSubTab(segment as MatchesSubTabKey, { hasFfaStage });

  // The URL itself is corrected only once the stages are in: they are unknown
  // on the first paint, and bouncing on that would kick an organizer off the
  // view they linked to.
  useEffect(() => {
    if (!stagesQuery.data || activeAllowed) return;
    router.replace(`${basePath}/${MATCHES_SUB_TABS[0]}`);
  }, [stagesQuery.data, activeAllowed, basePath, router]);

  const items: LinkTabItem[] = MATCHES_SUB_TABS.map((key) => ({
    key,
    label: SUB_TAB_LABELS[key],
    href: scopeQuery ? `${basePath}/${key}?${scopeQuery}` : `${basePath}/${key}`,
    hidden: !allowedMatchesSubTab(key, { hasFfaStage }),
    badge:
      key === "reports"
        ? disputed || undefined
        : key === "logs"
          ? logQueue || undefined
          : undefined
  }));

  return (
    <div className="space-y-4">
      <LinkTabs items={items} activeKey={segment} level={2} ariaLabel="Matches views" />
      {activeAllowed ? children : null}
    </div>
  );
}
