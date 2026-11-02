"use client";

import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

/**
 * The flags that decide how the tournament is counted. Points per result
 * are set per stage, in the bracket's stage settings.
 */
export default function ScoringSettingsPage() {
  return (
    <SettingsSectionPage section="scoring">
      {({ tournament, tournamentId, canUpdateTournament }) => (
        <ScoringForm
          tournament={tournament}
          tournamentId={tournamentId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function ScoringForm({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const t = useTranslations("adminTournament.scoring");
  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "scoring"
  );

  return (
    <>
      <div className="flex flex-col gap-4">
        <SettingGroup id="results" title={t("results")}>
          <SettingRow htmlFor="settings-is-league" label={t("league")}>
            <Switch
              id="settings-is-league"
              checked={form.is_league}
              disabled={disabled}
              onCheckedChange={(checked) => patch({ is_league: checked })}
            />
          </SettingRow>
          <SettingRow htmlFor="settings-is-finished" label={t("finished")}>
            <Switch
              id="settings-is-finished"
              checked={form.is_finished}
              disabled={disabled}
              onCheckedChange={(checked) => patch({ is_finished: checked })}
            />
          </SettingRow>
          <SettingRow
            htmlFor="settings-logs-official"
            label={t("logsOfficial")}
            hint={t("logsOfficialDescription")}
          >
            <Switch
              id="settings-logs-official"
              checked={form.logs_official}
              disabled={disabled}
              onCheckedChange={(checked) => patch({ logs_official: checked })}
            />
          </SettingRow>
        </SettingGroup>
      </div>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
