"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePermissions } from "@/hooks/usePermissions";
import { useTournamentRealtime } from "@/hooks/useTournamentRealtime";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { TournamentWorkspaceHeader } from "./components/TournamentWorkspaceHeader";

type TournamentWorkspaceTab =
  | "overview"
  | "teams"
  | "matches"
  | "logs"
  | "draft"
  | "veto"
  | "settings";
const TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS = 60_000;

const tabFallback = (
  <div className="space-y-4">
    <Skeleton className="h-32 w-full rounded-xl" />
    <Skeleton className="h-64 w-full rounded-xl" />
  </div>
);

const TournamentSetupTab = dynamic(
  () =>
    import("./components/TournamentSetupTab").then((module) => ({
      default: module.TournamentSetupTab
    })),
  { loading: () => tabFallback }
);

const TournamentTeamsTab = dynamic(
  () =>
    import("./components/TournamentTeamsTab").then((module) => ({
      default: module.TournamentTeamsTab
    })),
  { loading: () => tabFallback }
);

const TournamentMatchesTab = dynamic(
  () =>
    import("./components/TournamentMatchesTab").then((module) => ({
      default: module.TournamentMatchesTab
    })),
  { loading: () => tabFallback }
);

const TournamentLogsTab = dynamic(
  () =>
    import("./components/TournamentLogsTab").then((module) => ({
      default: module.TournamentLogsTab
    })),
  { loading: () => tabFallback }
);

const DraftSessionDashboard = dynamic(
  () =>
    import("./components/DraftSessionDashboard").then((module) => ({
      default: module.DraftSessionDashboard
    })),
  { loading: () => tabFallback }
);

const TournamentSettingsTab = dynamic(
  () =>
    import("./components/TournamentSettingsTab").then((module) => ({
      default: module.TournamentSettingsTab
    })),
  { loading: () => tabFallback }
);

const TournamentMapVetoTab = dynamic(
  () =>
    import("./components/TournamentMapVetoTab").then((module) => ({
      default: module.TournamentMapVetoTab
    })),
  { loading: () => tabFallback }
);


function UnauthorizedTournamentWorkspaceState() {
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

export default function AdminTournamentWorkspacePage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const isValidTournamentId = Number.isFinite(tournamentId) && tournamentId > 0;
  const { canAccessPermission, isLoaded: permissionsLoaded, isSuperuser } = usePermissions();
  const [activeTab, setActiveTab] = useState<TournamentWorkspaceTab>("overview");
  const shouldLoadTeams = activeTab === "teams" || activeTab === "matches";
  const shouldLoadEncounters = activeTab === "matches" || activeTab === "logs";
  const shouldLoadStandings = activeTab === "overview" || activeTab === "matches";

  const tournamentQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId],
    queryFn: () => adminService.getTournament(tournamentId),
    enabled: isValidTournamentId
  });

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

  const teamsQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "teams"],
    queryFn: () => teamService.getAll({ tournamentId }),
    enabled: isValidTournamentId && shouldLoadTeams
  });

  const stagesQuery = useQuery({
    queryKey: ["admin", "stages", tournamentId],
    queryFn: () => adminService.getStages(tournamentId),
    enabled: isValidTournamentId
  });

  const divisionGridsQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "division-grids"],
    queryFn: async () => {
      const workspaceId = tournamentQuery.data?.workspace_id;
      if (!workspaceId) return [];
      return workspaceService.getDivisionGrids(workspaceId);
    },
    enabled: Boolean(tournamentQuery.data?.workspace_id)
  });

  const standingsQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "standings"],
    queryFn: () =>
      tournamentService.getStandings(tournamentId, {
        includeMatchesHistory: false,
        includeTeamGroup: false
      }),
    enabled: isValidTournamentId && shouldLoadStandings,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true
  });

  const encountersQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "encounters"],
    queryFn: () => encounterService.getAll(1, "", tournamentId, -1),
    enabled: isValidTournamentId && shouldLoadEncounters,
    refetchInterval: TOURNAMENT_WORKSPACE_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: true
  });

  const discordChannelQuery = useQuery({
    queryKey: ["admin", "tournament", tournamentId, "discord-channel"],
    queryFn: () => adminService.getDiscordChannel(tournamentId),
    enabled: isValidTournamentId && activeTab === "overview"
  });

  const tournamentWorkspaceId = tournamentQuery.data?.workspace_id ?? null;
  useTournamentRealtime({
    tournamentId: isValidTournamentId ? tournamentId : null,
    workspaceId: tournamentWorkspaceId
  });

  const tournament = tournamentQuery.data;
  const canUpdateTournament = canAccessPermission("tournament.update", tournamentWorkspaceId);
  const canDeleteTournament = canAccessPermission("tournament.delete", tournamentWorkspaceId);
  const canReadAnalytics = canAccessPermission("analytics.read", tournamentWorkspaceId);
  const canCreateTeam = canAccessPermission("team.create", tournamentWorkspaceId);
  const canUpdateTeam = canAccessPermission("team.update", tournamentWorkspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", tournamentWorkspaceId);
  const canImportTeams = canAccessPermission("team.import", tournamentWorkspaceId);
  const canCreatePlayer = canAccessPermission("player.create", tournamentWorkspaceId);
  const canUpdatePlayer = canAccessPermission("player.update", tournamentWorkspaceId);
  const canDeletePlayer = canAccessPermission("player.delete", tournamentWorkspaceId);
  const canCreateEncounter = canAccessPermission("match.create", tournamentWorkspaceId);
  const canUpdateEncounter = canAccessPermission("match.update", tournamentWorkspaceId);
  const canDeleteEncounter = canAccessPermission("match.delete", tournamentWorkspaceId);
  const canSyncEncounters = canAccessPermission("match.sync", tournamentWorkspaceId);
  const canUpdateStanding = canAccessPermission("standing.update", tournamentWorkspaceId);
  const canDeleteStanding = canAccessPermission("standing.delete", tournamentWorkspaceId);
  const canRecalculateStandings = canAccessPermission(
    "standing.recalculate",
    tournamentWorkspaceId
  );
  const teams = teamsQuery.data?.results ?? [];
  const teamsCount = teamsQuery.data?.total ?? teamsCountQuery.data ?? null;
  const stages = stagesQuery.data ?? [];
  const standings = standingsQuery.data ?? [];
  const standingsCount = standingsQuery.data?.length ?? null;
  const encounters = encountersQuery.data?.results ?? [];
  const encountersCount = encountersQuery.data?.total ?? encountersCountQuery.data ?? null;
  const divisionGridVersions: DivisionGridVersion[] = (divisionGridsQuery.data ?? [])
    .flatMap((grid) => grid.versions)
    .slice()
    .sort((left, right) => right.version - left.version);
  const hasChallongeSource = Boolean(
    tournament?.challonge_slug || stages.some((stage) => Boolean(stage.challonge_slug))
  );

  if (tournamentQuery.isLoading || stagesQuery.isLoading || !permissionsLoaded) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-28 w-full rounded-xl" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
        <Skeleton className="h-96 w-full rounded-xl" />
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
      canRecalculateStandings
    ].some(Boolean)
  ) {
    return <UnauthorizedTournamentWorkspaceState />;
  }

  return (
    <div className="space-y-4">
      <TournamentWorkspaceHeader
        tournament={tournament}
        tournamentId={tournamentId}
        teamsCount={teamsCount}
        teamsCountLoading={teamsCount == null && teamsCountQuery.isLoading}
        encountersCount={encountersCount}
        encountersCountLoading={encountersCount == null && encountersCountQuery.isLoading}
        standingsCount={standingsCount}
        standingsCountLoading={standingsCount == null && standingsQuery.isLoading}
        canReadAnalytics={canReadAnalytics}
        canUpdateTournament={canUpdateTournament}
        canDeleteTournament={canDeleteTournament}
        canToggleFinished={canUpdateTournament && isSuperuser}
        divisionGridVersions={divisionGridVersions}
        divisionGridLoading={divisionGridsQuery.isLoading}
        onEditClick={() => setActiveTab("settings")}
      />

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as TournamentWorkspaceTab)}
        className="space-y-4"
      >
        <TabsList className="h-auto flex-wrap justify-start">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="teams">Teams</TabsTrigger>
          <TabsTrigger value="matches">Play & Results</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
          {tournament.team_formation === "draft" ? (
            <TabsTrigger value="draft">Draft</TabsTrigger>
          ) : null}
          {canUpdateEncounter ? <TabsTrigger value="veto">Map Veto</TabsTrigger> : null}
          {canUpdateTournament ? (
            <TabsTrigger value="settings">Settings</TabsTrigger>
          ) : null}
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          {activeTab === "overview" ? (
            <TournamentSetupTab
              tournamentId={tournamentId}
              tournament={tournament}
              stages={stages}
              hasChallongeSource={hasChallongeSource}
              canUpdateTournament={canUpdateTournament}
              discordChannel={discordChannelQuery.data}
              discordChannelLoading={discordChannelQuery.isLoading}
            />
          ) : null}
        </TabsContent>

        <TabsContent value="teams" className="space-y-4">
          {activeTab !== "teams" ? null : teamsQuery.isLoading ? (
            tabFallback
          ) : (
            <TournamentTeamsTab
              tournamentId={tournamentId}
              workspaceId={tournamentWorkspaceId}
              teams={teams}
              stagesCount={stages.length}
              hasChallongeSource={hasChallongeSource}
              canCreateTeam={canCreateTeam}
              canUpdateTeam={canUpdateTeam}
              canDeleteTeam={canDeleteTeam}
              canImportTeams={canImportTeams}
              canCreatePlayer={canCreatePlayer}
              canUpdatePlayer={canUpdatePlayer}
              canDeletePlayer={canDeletePlayer}
            />
          )}
        </TabsContent>

        <TabsContent value="matches" className="space-y-4">
          {activeTab !== "matches" ? null : teamsQuery.isLoading ||
            standingsQuery.isLoading ||
            encountersQuery.isLoading ? (
            tabFallback
          ) : (
            <TournamentMatchesTab
              tournamentId={tournamentId}
              teams={teams}
              stages={stages}
              encounters={encounters}
              standings={standings}
              hasChallongeSource={hasChallongeSource}
              canCreateEncounter={canCreateEncounter}
              canUpdateEncounter={canUpdateEncounter}
              canDeleteEncounter={canDeleteEncounter}
              canSyncEncounters={canSyncEncounters}
              canUpdateStanding={canUpdateStanding}
              canDeleteStanding={canDeleteStanding}
              canRecalculateStandings={canRecalculateStandings}
            />
          )}
        </TabsContent>

        <TabsContent value="logs" className="space-y-4">
          {activeTab !== "logs" ? null : encountersQuery.isLoading ? (
            tabFallback
          ) : (
            <TournamentLogsTab
              tournamentId={tournamentId}
              encounters={encounters}
              canUploadLogs={canUpdateEncounter}
              enabled={activeTab === "logs"}
            />
          )}
        </TabsContent>

        {tournament.team_formation === "draft" ? (
          <TabsContent value="draft" className="space-y-4">
            {activeTab === "draft" ? (
              <DraftSessionDashboard tournamentId={tournamentId} canManage={canImportTeams} />
            ) : null}
          </TabsContent>
        ) : null}

        {canUpdateEncounter ? (
          <TabsContent value="veto" className="space-y-4">
            {activeTab === "veto" ? (
              <TournamentMapVetoTab
                tournamentId={tournamentId}
                stages={stages}
                canManage={canUpdateEncounter}
              />
            ) : null}
          </TabsContent>
        ) : null}

        {canUpdateTournament ? (
          <TabsContent value="settings" className="space-y-4">
            {activeTab === "settings" ? (
              <TournamentSettingsTab
                tournament={tournament}
                tournamentId={tournamentId}
                divisionGridVersions={divisionGridVersions}
                divisionGridLoading={divisionGridsQuery.isLoading}
                canDeleteTournament={canDeleteTournament}
              />
            ) : null}
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}
