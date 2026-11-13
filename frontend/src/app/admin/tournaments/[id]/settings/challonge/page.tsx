"use client";

import { useTranslations } from "next-intl";

import { SaveBar } from "@craazzzyyfoxx/admin-kit/kit/SaveBar";
import { SettingGroup, SettingsGrid } from "@/components/kit/SettingRow";
import { hasChallongeSource } from "@/components/admin/tournament-checklist";
import type { Tournament } from "@/types/tournament.types";
import { ChallongeIntegrationSection } from "../../components/ChallongeIntegrationSection";
import { useHubStagesQuery } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";
import { useUnsavedReporter } from "@/components/kit/SettingsContinuation";

export default function ChallongeSettingsPage() {
  return (
    <SettingsSectionPage section="challonge">
      {({ tournament, tournamentId }) => (
        <ChallongeSettings tournament={tournament} tournamentId={tournamentId} />
      )}
    </SettingsSectionPage>
  );
}

function ChallongeSettings({
  tournament,
  tournamentId
}: Readonly<{ tournament: Tournament; tournamentId: number }>) {
  const reportUnsaved = useUnsavedReporter();
  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "challonge"
  );
  const t = useTranslations("adminTournament.challonge");
  const stagesQuery = useHubStagesQuery(tournamentId);

  return (
    <>
      <SettingsGrid>
      <SettingGroup id="sync" title={t("groups.sync.title")}>
        {/* The slug is a tournament field, so it saves through the section's
            own bar; import/export fire their own mutations from inside. */}
        <ChallongeIntegrationSection
          tournamentId={tournamentId}
          hasChallongeSource={hasChallongeSource(tournament, stagesQuery.data ?? [])}
          slug={form.challonge_slug}
          onSlugChange={(value) => patch({ challonge_slug: value })}
        />
      </SettingGroup>
      </SettingsGrid>

      <SaveBar onDirtyChange={reportUnsaved} dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
