"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminTabs, type AdminTabItem } from "@/components/admin/kit/AdminTabs";
import { EntityHubHeader } from "@/components/admin/kit/EntityHubHeader";
import { usePermissions } from "@/hooks/usePermissions";
import { useInvalidation } from "@/hooks/useInvalidation";
import { useSyncActiveWorkspace } from "@/hooks/useSyncActiveWorkspace";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { TOURNAMENT_STATUS_LABELS } from "@/lib/tournament-lifecycle";
import encounterService from "@/services/encounter.service";
import teamService from "@/services/team.service";
import { TournamentHubActions } from "./components/TournamentHubActions";
import { formatDate, TOURNAMENT_STATUS_TONE } from "./components/tournamentWorkspace.helpers";
import { getTournamentWorkspaceQueryKeys } from "./components/tournamentWorkspace.queryKeys";
import {
  TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
  useHubStagesQuery,
  useHubStandingsQuery,
  useHubTournamentQuery
} from "./hubQueries";
import { allowedTab, isLegacyTabSegment, isTabKey, TAB_KEYS, type TabKey } from "./tab-guards";

/**
 * Hub tabs are the tournament's lifecycle, in the order it happens (§5).
 *
 * Four entries left the bar: `stages` became `bracket`, `draft` a sub-tab of
 * `teams`, and `pickBan`/`links` sections of `settings` — configuration is not
 * a phase, and the bar was nine items wide because it pretended otherwise.
 */
const TAB_LABELS: Record<TabKey, string> = {
  overview: "Overview",
  registration: "Registration",
  teams: "Teams",
  bracket: "Bracket",
  matches: "Matches",
  settings: "Settings"
};

// Trailing debounce for readiness invalidations (§3): bulk registration edits
// flush the tournament and the workspace scope back to back — a burst must cost
// one readiness refetch, not N.
const READINESS_INVALIDATE_DEBOUNCE_MS = 400;

/**
 * Client shell of the tournament hub (§1.1): owns the permission gate, the
 * workspace header, the tab bar with route guards, the hub's two
 * `useInvalidation` mounts and the shared queries. Query keys MUST stay
 * identical to the tab pages — realtime patch-in-cache and workspace
 * invalidation depend on them (see components/tournamentWorkspace.queryKeys.ts).
 */
export function TournamentHubShell({
  tournamentId,
  children
}: Readonly<{
  tournamentId: number;
  children: ReactNode;
}>) {
  const router = useRouter();
  const pathname = usePathname();
  const isValidTournamentId = Number.isFinite(tournamentId) && tournamentId > 0;
  const { canAccessPermission, isLoaded: permissionsLoaded, isSuperuser } = usePermissions();

  const basePath = `/admin/tournaments/${tournamentId}`;
  // Segment right after the id is the tab; deeper segments (sub-tabs like
  // registration/entries) still resolve to their parent tab. A segment that
  // used to be a tab and has not moved yet highlights nothing rather than
  // pretending to be Overview.
  const tabSegment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? "overview")
    : "overview";
  const isLegacySegment = isLegacyTabSegment(tabSegment);
  const activeTab: TabKey = isTabKey(tabSegment) ? tabSegment : "overview";

  const tournamentQuery = useHubTournamentQuery(tournamentId);

  const teamsCountQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "teams", "count"],
    queryFn: () => teamService.getCount(tournamentId),
    enabled: isValidTournamentId,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true
  });

  const encountersCountQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "encounters", "count"],
    queryFn: () => encounterService.getCount(tournamentId),
    enabled: isValidTournamentId,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true
  });

  const stagesQuery = useHubStagesQuery(tournamentId);
  // Pre-T5 the standings query was gated to the overview|matches tabs, but the
  // header shows the standings metric unconditionally — keep it always enabled.
  const standingsQuery = useHubStandingsQuery(tournamentId);

  const tournamentWorkspaceId = tournamentQuery.data?.workspace_id ?? null;
  // Align the workspace store with the tournament's workspace: workspace-scoped
  // catalogs (custom statuses, sub-roles) on the registration tab read the store,
  // and apiFetch injects the store workspace into every call (D25/D29).
  useSyncActiveWorkspace(tournamentWorkspaceId);
  // NOTE: no division-grid query here. It used to run on every hub page load
  // purely to feed three header props that were never read. The Settings tab
  // owns that query, where the grid picker actually uses it.

  // Living-checklist freshness (§3, G-O6): the readiness aggregate is derived
  // from registrations, teams and stages, but it is not a resource of its own —
  // no publisher names it. So it rides on every invalidation flush of this
  // tournament, debounced once here (a bulk registration edit is one flush per
  // coalescing window, but the workspace scope can flush independently).
  const queryClient = useQueryClient();
  const readinessTimerRef = useRef<number | undefined>(undefined);
  const scheduleReadinessInvalidate = useCallback(() => {
    window.clearTimeout(readinessTimerRef.current);
    readinessTimerRef.current = window.setTimeout(() => {
      void queryClient.invalidateQueries({
        queryKey: getTournamentWorkspaceQueryKeys(tournamentId).readiness
      });
    }, READINESS_INVALIDATE_DEBOUNCE_MS);
  }, [queryClient, tournamentId]);
  useEffect(() => () => window.clearTimeout(readinessTimerRef.current), []);

  // The one and only realtime mount of the hub — tab pages must not mount it.
  useInvalidation({
    scopeKind: "tournament",
    scopeId: isValidTournamentId ? tournamentId : null,
    workspaceId: tournamentWorkspaceId,
    onFlush: scheduleReadinessInvalidate
  });

  // Subscription verdicts ride on every registration read (`subscription_outcome`
  // drives the admission grouping), so a background sweep or another admin's
  // re-check changes this page with no local mutation to hang an invalidation on.
  // Workspace-scoped, not tournament-scoped: an entitlement is
  // (workspace, user, provider) and one change is visible in every tournament —
  // which is also why `workspace.subscriptions` cannot name this tournament's
  // registration list, and the hub re-reads it here instead.
  useInvalidation({
    scopeKind: "workspace",
    scopeId: tournamentWorkspaceId,
    tournamentId: isValidTournamentId ? tournamentId : null,
    onFlush: (resources) => {
      if (tournamentWorkspaceId == null || !resources.includes("workspace.subscriptions")) return;
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationsList(tournamentWorkspaceId, tournamentId)
      });
      scheduleReadinessInvalidate();
    }
  });

  const tournament = tournamentQuery.data;
  const canUpdateTournament = canAccessPermission("tournament.update", tournamentWorkspaceId);
  const canDeleteTournament = canAccessPermission("tournament.delete", tournamentWorkspaceId);
  const canReadAnalytics = canAccessPermission("analytics.read", tournamentWorkspaceId);
  const canTeamRead = canAccessPermission("team.read", tournamentWorkspaceId);
  const canReadTournamentLink = canAccessPermission(
    "tournament_link.read",
    tournamentWorkspaceId
  );
  const canCreateTeam = canAccessPermission("team.create", tournamentWorkspaceId);
  const canUpdateTeam = canAccessPermission("team.update", tournamentWorkspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", tournamentWorkspaceId);
  const canImportTeams = canAccessPermission("team.create", tournamentWorkspaceId);
  const canCreatePlayer = canAccessPermission("player.create", tournamentWorkspaceId);
  const canUpdatePlayer = canAccessPermission("player.update", tournamentWorkspaceId);
  const canDeletePlayer = canAccessPermission("player.delete", tournamentWorkspaceId);
  const canCreateEncounter = canAccessPermission("match.create", tournamentWorkspaceId);
  const canUpdateEncounter = canAccessPermission("match.update", tournamentWorkspaceId);
  const canDeleteEncounter = canAccessPermission("match.delete", tournamentWorkspaceId);
  const canSyncEncounters = canAccessPermission("challonge.update", tournamentWorkspaceId);
  const canUpdateStanding = canAccessPermission("standing.update", tournamentWorkspaceId);
  const canDeleteStanding = canAccessPermission("standing.delete", tournamentWorkspaceId);
  const canRecalculateStandings = canAccessPermission(
    "standing.update",
    tournamentWorkspaceId
  );

  const teamFormation: "balancer" | "draft" =
    tournament?.team_formation === "draft" ? "draft" : "balancer";
  const tabAccess = {
    canUpdateTournament,
    canUpdateEncounter,
    canTeamRead,
    canReadTournamentLink,
    canDeleteTournament,
    teamFormation
  };
  // A segment awaiting its WU is not a tab, so it has no tab gate to fail —
  // its own page keeps gating itself until the move.
  const activeTabAllowed = isLegacySegment || allowedTab(activeTab, tabAccess);

  // Route guard (D2): a direct hit on a tab the caller may not open bounces
  // back to overview. Only decide once permissions and the tournament are in.
  useEffect(() => {
    if (!permissionsLoaded || !tournament) return;
    if (!activeTabAllowed) {
      router.replace(`${basePath}/overview`);
    }
  }, [permissionsLoaded, tournament, activeTabAllowed, basePath, router]);

  const teamsCount = teamsCountQuery.data ?? null;
  const encountersCount = encountersCountQuery.data ?? null;
  const standingsCount = standingsQuery.data?.length ?? null;

  if (tournamentQuery.isLoading || stagesQuery.isLoading || !permissionsLoaded) {
    return (
      // Mirrors the real shape: title bar, phase stepper, tab bar, tab body.
      <div className="space-y-4">
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-14 w-full rounded-xl" />
        <Skeleton className="h-9 w-full max-w-2xl rounded-lg" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    );
  }

  if (!tournament) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Tournament not found</CardTitle>
          <CardDescription>The requested admin workspace could not be loaded.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (
    !isSuperuser &&
    ![
      canUpdateTournament,
      canDeleteTournament,
      canReadAnalytics,
      canCreateTeam,
      canUpdateTeam,
      canDeleteTeam,
      canImportTeams,
      canCreatePlayer,
      canUpdatePlayer,
      canDeletePlayer,
      canCreateEncounter,
      canUpdateEncounter,
      canDeleteEncounter,
      canSyncEncounters,
      canUpdateStanding,
      canDeleteStanding,
      canRecalculateStandings,
      // Otherwise a caller granted only `tournament_link.read` sees
      // "Unauthorized" instead of the Links tab `allowedTab` just cleared.
      canReadTournamentLink
    ].some(Boolean)
  ) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unauthorized</CardTitle>
          <CardDescription>
            You do not have permission to access this tournament workspace.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const tabItems: AdminTabItem[] = TAB_KEYS.map((key) => ({
    key,
    label: TAB_LABELS[key],
    href: `${basePath}/${key}`,
    hidden: !allowedTab(key, tabAccess)
  }));

  return (
    <div className="space-y-4">
      <EntityHubHeader
        title={tournament.name}
        status={{
          label: TOURNAMENT_STATUS_LABELS[tournament.status],
          tone: TOURNAMENT_STATUS_TONE[tournament.status]
        }}
        meta={[
          <span key="dates" className="tabular-nums">
            {formatDate(tournament.start_date)} — {formatDate(tournament.end_date)}
          </span>,
          tournament.is_league ? "League" : null,
          <span key="teams" className="tabular-nums">
            {formatMetric(teamsCount, teamsCountQuery.isLoading)} teams
          </span>,
          <span key="encounters" className="tabular-nums">
            {formatMetric(encountersCount, encountersCountQuery.isLoading)} encounters
          </span>,
          <span key="standings" className="tabular-nums">
            {formatMetric(standingsCount, standingsQuery.isLoading)} standings
          </span>
        ]}
        actions={
          <TournamentHubActions
            tournament={tournament}
            tournamentId={tournamentId}
            canReadAnalytics={canReadAnalytics}
            canUpdateTournament={canUpdateTournament}
            canToggleFinished={canUpdateTournament && isSuperuser}
          />
        }
      />
      <AdminTabs items={tabItems} activeKey={isLegacySegment ? "" : activeTab} ariaLabel="Tournament sections" />
      {activeTabAllowed ? children : null}
    </div>
  );
}

/** `12`, `…` while loading, `—` when the count is unavailable. */
function formatMetric(value: number | null, isLoading: boolean) {
  if (typeof value === "number") return String(value);
  return isLoading ? "…" : "—";
}
