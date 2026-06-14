"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Shield, Swords, Trophy, UserCircle, Users } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";
import { useLogStream } from "@/hooks/useLogStream";
import { apiFetch } from "@/lib/api-fetch";
import tournamentService from "@/services/tournament.service";
import type { PaginatedResponse } from "@/types/pagination.types";
import type { Tournament } from "@/types/tournament.types";

import { GreetingBar } from "@/components/admin/dashboard/GreetingBar";
import { KpiStrip } from "@/components/admin/dashboard/KpiStrip";
import { ActiveTournamentCard } from "@/components/admin/dashboard/ActiveTournamentCard";
import { LogProcessingQueue } from "@/components/admin/dashboard/LogProcessingQueue";
import { IssuesQueue, type IssueItem } from "@/components/admin/dashboard/IssuesQueue";
import { RecentTournaments } from "@/components/admin/dashboard/RecentTournaments";
import { QuickAccessGrid, type QuickAccessItem } from "@/components/admin/dashboard/QuickAccessGrid";

interface DashboardActiveTournamentStats {
  tournament_id: number;
  encounters_total: number;
  encounters_missing_logs: number;
  log_coverage_percent: number;
}

interface DashboardIssues {
  encounters_missing_logs: number;
  teams_without_players: number;
  tournaments_without_stages: number;
  users_without_identities: number;
}

interface DashboardStats {
  tournaments_total: number;
  tournaments_active: number;
  teams_total: number;
  players_total: number;
  encounters_total: number;
  heroes_total: number;
  gamemodes_total: number;
  maps_total: number;
  active_tournament_stats: DashboardActiveTournamentStats | null;
  issues: DashboardIssues;
}

function emptyPaginated<T>(): PaginatedResponse<T> {
  return { results: [], total: 0, page: 1, per_page: 0 };
}

function isDefined<T>(value: T | null): value is T {
  return value !== null;
}

export default function AdminDashboard() {
  const { canAccessPermission, hasPermission } = usePermissions();
  const workspaceId = useCurrentWorkspaceId();

  const canReadTournaments = canAccessPermission("tournament.read", workspaceId);
  const canReadTeams = canAccessPermission("team.read", workspaceId);
  const canReadPlayers = canAccessPermission("player.read", workspaceId);
  const canReadMatches = canAccessPermission("match.read", workspaceId);
  const canReadStandings = canAccessPermission("standing.read", workspaceId);
  const canReadUsers = canAccessPermission("user.read", workspaceId);
  const canReadAccessUsers = hasPermission("auth_user.read");
  const canReadHeroes = canAccessPermission("hero.read", workspaceId);
  const canReadGamemodes = canAccessPermission("gamemode.read", workspaceId);
  const canReadMaps = canAccessPermission("map.read", workspaceId);
  const canReadRoles = hasPermission("role.read");
  const canReadPermissions = hasPermission("permission.read");

  const accessAdminHref = canReadAccessUsers
    ? "/admin/access/users"
    : canReadRoles
      ? "/admin/access/roles"
      : canReadPermissions
        ? "/admin/access/permissions"
        : null;

  const logStream = useLogStream(true, workspaceId);

  // Aggregated counts from backend (single lightweight query)
  const statsQuery = useQuery({
    queryKey: ["admin", "dashboard", "stats"],
    queryFn: () =>
      apiFetch("app", "statistics/dashboard").then(
        (r) => r.json() as Promise<DashboardStats>,
      ),
  });

  // Tournaments still needed for Active Tournament Card & Recent Tournaments display
  const tournamentsQuery = useQuery({
    queryKey: ["admin", "dashboard", "tournaments"],
    queryFn: () =>
      canReadTournaments
        ? tournamentService.getAll(null)
        : Promise.resolve(emptyPaginated<Tournament>()),
  });

  const stats = statsQuery.data;
  const tournaments = tournamentsQuery.data?.results ?? [];

  const derived = useMemo(() => {
    const activeTournament = canReadTournaments
      ? (tournaments.find((t) => !t.is_finished) ?? tournaments[0] ?? null)
      : null;

    const activeStats = stats?.active_tournament_stats;
    const encounterCount = activeStats?.encounters_total ?? 0;
    const missingLogs = activeStats?.encounters_missing_logs ?? 0;
    const logCoveragePercent = activeStats?.log_coverage_percent ?? 100;

    const issues = stats?.issues;
    const issueItems: IssueItem[] = [
      canReadMatches && (issues?.encounters_missing_logs ?? 0) > 0
        ? { label: "Missing encounter logs", count: issues!.encounters_missing_logs, href: "/admin/encounters", tone: "critical" as const }
        : null,
      canReadTeams && (issues?.teams_without_players ?? 0) > 0
        ? { label: "Teams without rosters", count: issues!.teams_without_players, href: "/admin/teams", tone: "warning" as const }
        : null,
      canReadTournaments && (issues?.tournaments_without_stages ?? 0) > 0
        ? { label: "Tournaments missing stages", count: issues!.tournaments_without_stages, href: "/admin/tournaments", tone: "warning" as const }
        : null,
      canReadUsers && (issues?.users_without_identities ?? 0) > 0
        ? { label: "Unlinked player identities", count: issues!.users_without_identities, href: "/admin/users", tone: "info" as const }
        : null,
    ].filter((item): item is IssueItem => item !== null);

    return {
      activeTournament,
      encounterCount,
      missingLogs,
      logCoveragePercent,
      issueItems,
    };
  }, [stats, tournaments, canReadMatches, canReadTeams, canReadTournaments, canReadUsers]);

  // Quick access items (6 max, no descriptions)
  const quickAccessItems: QuickAccessItem[] = [
    canReadTournaments ? { href: "/admin/tournaments", title: "Tournaments", icon: Trophy } : null,
    canReadTeams ? { href: "/admin/teams", title: "Teams", icon: Users } : null,
    canReadMatches ? { href: "/admin/encounters", title: "Encounters", icon: Swords } : null,
    canReadPlayers ? { href: "/admin/players", title: "Players", icon: UserCircle } : null,
    canReadStandings ? { href: "/admin/standings", title: "Standings", icon: BarChart3 } : null,
    accessAdminHref ? { href: accessAdminHref, title: "Access & Roles", icon: Shield } : null,
  ].filter(isDefined);

  // KPI data
  const hasContentInventory = canReadHeroes || canReadMaps || canReadGamemodes;

  if (statsQuery.isLoading || tournamentsQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-14 rounded-2xl" />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
        <div className="grid gap-4 xl:grid-cols-[7fr_3fr]">
          <div className="flex flex-col gap-4">
            <Skeleton className="h-56 rounded-2xl" />
            <Skeleton className="h-64 rounded-2xl" />
          </div>
          <div className="flex flex-col gap-4">
            <Skeleton className="h-48 rounded-2xl" />
            <Skeleton className="h-48 rounded-2xl" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* [1] GREETING BAR */}
      <GreetingBar canCreateTournament={canReadTournaments} />

      {/* [2] KPI STRIP */}
      <KpiStrip
        tournaments={
          canReadTournaments
            ? { active: stats?.tournaments_active ?? 0, total: stats?.tournaments_total ?? 0 }
            : null
        }
        teams={canReadTeams ? (stats?.teams_total ?? 0) : null}
        players={canReadTeams ? (stats?.players_total ?? 0) : null}
        encounters={canReadMatches ? (stats?.encounters_total ?? 0) : null}
        content={
          hasContentInventory
            ? { heroes: stats?.heroes_total ?? 0, maps: stats?.maps_total ?? 0, gamemodes: stats?.gamemodes_total ?? 0 }
            : null
        }
      />

      {/* [3] TWO-COLUMN SPLIT */}
      <section className="grid gap-4 xl:grid-cols-[7fr_3fr]">
        {/* LEFT COLUMN */}
        <div className="flex flex-col gap-4">
          <ActiveTournamentCard
            canRead={canReadTournaments}
            tournament={derived.activeTournament}
            encounterCount={derived.encounterCount}
            missingLogs={derived.missingLogs}
            logCoveragePercent={derived.logCoveragePercent}
            canReadMatches={canReadMatches}
          />
          <LogProcessingQueue logStream={logStream} />
        </div>

        {/* RIGHT COLUMN */}
        <div className="flex flex-col gap-4">
          <IssuesQueue items={derived.issueItems} />
          <RecentTournaments
            canRead={canReadTournaments}
            tournaments={tournaments}
          />
        </div>
      </section>

      {/* [4] QUICK ACCESS */}
      <QuickAccessGrid items={quickAccessItems} />
    </div>
  );
}
