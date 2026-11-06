"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { isNotFoundError } from "@/lib/api/error";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { usePermissions } from "@/hooks/usePermissions";
import { useInvalidation } from "@/hooks/useInvalidation";
import { useSyncActiveWorkspace } from "@/hooks/useSyncActiveWorkspace";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { displayStatus } from "@/lib/tournament/status";
import { FlowNodeControls } from "@/components/tournaments/FlowNodeControls";
import { TournamentStatusControl } from "./components/TournamentStatusControl";
import { TOURNAMENT_STATUS_TONE } from "./components/tournamentWorkspace.helpers";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import {
  useHubEncountersCountQuery,
  useHubStagesQuery,
  useHubTeamsCountQuery,
  useHubTournamentQuery
} from "./hubQueries";
import { useSubTabSegment, useTabAccess } from "./sub-tabs";
import { allowedTab, isLegacyTabSegment, TAB_KEYS } from "./tab-guards";

// Trailing debounce for readiness invalidations (§3): bulk registration edits
// flush the tournament and the workspace scope back to back — a burst must cost
// one readiness refetch, not N.
const READINESS_INVALIDATE_DEBOUNCE_MS = 400;

/**
 * Client shell of the tournament hub (§1.1): owns the permission gate, the
 * workspace header, the tab bar with route guards, the hub's two
 * `useInvalidation` mounts and the shared queries. Query keys MUST stay
 * identical to the tab pages — realtime patch-in-cache and workspace
 * invalidation depend on them (see lib/tournament/workspace-query-keys.ts).
 */
export function TournamentHubShell({
  tournamentId,
  children
}: Readonly<{
  tournamentId: number;
  children: ReactNode;
}>) {
  const t = useTranslations("adminTournament.shell");
  const tStatus = useTranslations("common.statusBadge");
  const format = useFormatter();
  const router = useRouter();
  const isValidTournamentId = Number.isFinite(tournamentId) && tournamentId > 0;
  const { canAccessPermission, isLoaded: permissionsLoaded, isSuperuser } = usePermissions();

  const basePath = `/admin/tournaments/${tournamentId}`;
  // Segment right after the id is the tab; deeper segments (sub-tabs like
  // registration/entries) still resolve to their parent tab. A segment that
  // used to be a tab and has not moved yet highlights nothing rather than
  // pretending to be Overview.
  const { segment: tabSegment, active: activeTab } = useSubTabSegment(basePath, TAB_KEYS, "overview");
  const isLegacySegment = isLegacyTabSegment(tabSegment);

  const tournamentQuery = useHubTournamentQuery(tournamentId);

  const tournamentWorkspaceId = tournamentQuery.data?.workspace_id ?? null;

  const teamsCountQuery = useHubTeamsCountQuery(tournamentId, tournamentWorkspaceId);
  const encountersCountQuery = useHubEncountersCountQuery(tournamentId, tournamentWorkspaceId);

  const stagesQuery = useHubStagesQuery(tournamentId);

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
  const tabAccess = useTabAccess(tournament);
  const { canUpdateTournament, canDeleteTournament, canUpdateEncounter, canReadTournamentLink, canTeamCreate } =
    tabAccess;
  const canReadAnalytics = canAccessPermission("analytics.read", tournamentWorkspaceId);
  const canUpdateTeam = canAccessPermission("team.update", tournamentWorkspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", tournamentWorkspaceId);
  const canCreatePlayer = canAccessPermission("player.create", tournamentWorkspaceId);
  const canUpdatePlayer = canAccessPermission("player.update", tournamentWorkspaceId);
  const canDeletePlayer = canAccessPermission("player.delete", tournamentWorkspaceId);
  const canCreateEncounter = canAccessPermission("match.create", tournamentWorkspaceId);
  const canDeleteEncounter = canAccessPermission("match.delete", tournamentWorkspaceId);
  const canSyncEncounters = canAccessPermission("challonge.update", tournamentWorkspaceId);
  const canUpdateStanding = canAccessPermission("standing.update", tournamentWorkspaceId);
  const canDeleteStanding = canAccessPermission("standing.delete", tournamentWorkspaceId);
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

  const teamsCount = teamsCountQuery.data;
  const encountersCount = encountersCountQuery.data;

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
    // An invalid id never queries, and a 404 is an answer: both are not-found.
    // Anything else is a failed read the user can retry.
    return tournamentQuery.isError && !isNotFoundError(tournamentQuery.error) ? (
      <PageStateCard state="error" headingLevel={1} onAction={() => void tournamentQuery.refetch()} />
    ) : (
      <PageStateCard state="not-found" headingLevel={1} title={t("notFound")} description={t("notFoundDescription")} />
    );
  }

  if (
    !isSuperuser &&
    ![
      canUpdateTournament,
      canDeleteTournament,
      canReadAnalytics,
      canTeamCreate,
      canUpdateTeam,
      canDeleteTeam,
      canCreatePlayer,
      canUpdatePlayer,
      canDeletePlayer,
      canCreateEncounter,
      canUpdateEncounter,
      canDeleteEncounter,
      canSyncEncounters,
      canUpdateStanding,
      canDeleteStanding,
      // Otherwise a caller granted only `tournament_link.read` sees
      // "Unauthorized" instead of the Links tab `allowedTab` just cleared.
      canReadTournamentLink
    ].some(Boolean)
  ) {
    return (
      <PageStateCard
        state="not-found"
        headingLevel={1}
        title={t("unauthorized")}
        description={t("unauthorizedDescription")}
      />
    );
  }

  const tabItems: LinkTabItem[] = TAB_KEYS.map((key) => ({
    key,
    label: t(`tabs.${key}`),
    href: `${basePath}/${key}`,
    hidden: !allowedTab(key, tabAccess)
  }));

  return (
    <div className="space-y-4">
      <EntityHubHeader
        title={tournament.name}
        status={{
          label: tStatus(displayStatus(tournament)),
          tone: TOURNAMENT_STATUS_TONE[displayStatus(tournament)]
        }}
        meta={[
          <span key="dates" className="tabular-nums">
            {formatDateRange(format, tournament.start_date, tournament.end_date)}
          </span>,
          tournament.is_league ? t("league") : null,
          typeof teamsCount === "number" ? (
            <span key="teams" className="tabular-nums">
              {t("teamsMetric", { count: teamsCount })}
            </span>
          ) : null,
          typeof encountersCount === "number" ? (
            <span key="encounters" className="tabular-nums">
              {t("encountersMetric", { count: encountersCount })}
            </span>
          ) : null,
          canReadAnalytics ? (
            <Link
              key="analytics"
              href={`/tournaments/analytics?tournamentId=${tournament.id}`}
              className="underline-offset-4 hover:text-foreground hover:underline"
            >
              {t("openAnalytics")}
            </Link>
          ) : null
        ]}
        actions={
          <>
            <FlowNodeControls tournament={tournament} canUpdate={canUpdateTournament} />
            <TournamentStatusControl tournament={tournament} canUpdate={canUpdateTournament} />
          </>
        }
      />
      <LinkTabs items={tabItems} activeKey={isLegacySegment ? "" : activeTab} ariaLabel={t("sections")} />
      {activeTabAllowed ? children : null}
    </div>
  );
}
