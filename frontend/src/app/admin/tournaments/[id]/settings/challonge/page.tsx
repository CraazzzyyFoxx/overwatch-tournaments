"use client";

import { Card, CardContent } from "@/components/ui/card";
import { SaveBar } from "@/components/kit/SaveBar";
import { hasChallongeSource } from "@/components/admin/tournament-checklist";
import type { Tournament } from "@/types/tournament.types";
import { ChallongeIntegrationSection } from "../../components/ChallongeIntegrationSection";
import { useHubStagesQuery } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

export default function ChallongeSettingsPage() {
  return (
    <SettingsSectionPage
      section="challonge"
      description="The Challonge bracket this tournament imports from and exports to."
    >
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
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "challonge"
  );
  const stagesQuery = useHubStagesQuery(tournamentId);

  return (
    <>
      <Card>
        <CardContent className="pt-6">
          {/* The slug is a tournament field, so it saves through the section's
              own bar; import/export fire their own mutations from inside. */}
          <ChallongeIntegrationSection
            tournamentId={tournamentId}
            hasChallongeSource={hasChallongeSource(tournament, stagesQuery.data ?? [])}
            slug={form.challonge_slug}
            onSlugChange={(value) => patch({ challonge_slug: value })}
          />
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
