"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { TournamentDiscordSection } from "../../components/TournamentDiscordSection";
import { TournamentVoiceSection } from "../../components/TournamentVoiceSection";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

export default function DiscordSettingsPage() {
  return (
    <SettingsSectionPage section="discord">
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
  const t = useTranslations("adminTournament.discordSettings");
  const tChannel = useTranslations("adminTournament.discord");
  const tVoice = useTranslations("adminTournament.voiceSettings");
  const channelQuery = useQuery({
    queryKey: getTournamentWorkspaceQueryKeys(tournamentId).discordChannel,
    queryFn: () => adminService.getDiscordChannel(tournamentId)
  });

  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "discord"
  );

  return (
    <>
      <SettingsGrid>
      <SettingGroup id="notifications" title={t("groups.notifications.title")}>
        <SettingRow
          htmlFor="settings-discord-broadcasts"
          label={t("announcements")}
          hint={t("announcementsDescription")}
        >
          <Switch
            id="settings-discord-broadcasts"
            checked={form.discord_broadcasts_enabled}
            disabled={!canUpdateTournament}
            onCheckedChange={(checked) => patch({ discord_broadcasts_enabled: checked })}
          />
        </SettingRow>
        <SettingRow htmlFor="settings-discord-dms" label={t("messages")} hint={t("messagesDescription")}>
          <Switch
            id="settings-discord-dms"
            checked={form.discord_dms_enabled}
            disabled={!canUpdateTournament}
            onCheckedChange={(checked) => patch({ discord_dms_enabled: checked })}
          />
        </SettingRow>
      </SettingGroup>

      <SettingGroup id="match-logs" title={tChannel("title")} immediate>
        <TournamentDiscordSection
          tournamentId={tournamentId}
          tournament={tournament}
          canUpdateTournament={canUpdateTournament}
          discordChannel={channelQuery.data}
          discordChannelLoading={channelQuery.isLoading}
        />
      </SettingGroup>

      <SettingGroup id="voice-channels" title={tVoice("title")} description={tVoice("description")}>
        <TournamentVoiceSection
          tournamentId={tournamentId}
          workspaceId={tournament.workspace_id}
          canUpdateTournament={canUpdateTournament}
        />
      </SettingGroup>
      </SettingsGrid>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
