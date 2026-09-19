"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent } from "@/components/ui/card";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { TournamentDiscordSection } from "../../components/TournamentDiscordSection";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament-workspace-query-keys";
import { SettingsSectionPage } from "../SettingsSection";

export default function DiscordSettingsPage() {
  return (
    <SettingsSectionPage
      section="discord"
      description="The Discord channel this tournament reads match logs from."
    >
      {({ tournament, tournamentId, canUpdateTournament }) => (
        <DiscordSettings
          tournamentId={tournamentId}
          tournament={tournament}
          canUpdateTournament={canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function DiscordSettings({
  tournamentId,
  tournament,
  canUpdateTournament
}: Readonly<{
  tournamentId: number;
  tournament: Tournament;
  canUpdateTournament: boolean;
}>) {
  const channelQuery = useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).discordChannel,
    queryFn: () => adminService.getDiscordChannel(tournamentId)
  });

  return (
    <Card>
      <CardContent className="pt-6">
        <TournamentDiscordSection
          tournamentId={tournamentId}
          tournament={tournament}
          canUpdateTournament={canUpdateTournament}
          discordChannel={channelQuery.data}
          discordChannelLoading={channelQuery.isLoading}
        />
      </CardContent>
    </Card>
  );
}
