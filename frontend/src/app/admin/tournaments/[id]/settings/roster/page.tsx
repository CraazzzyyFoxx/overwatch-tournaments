"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { RosterShapeEditor } from "@/components/roster-shape/RosterShapeEditor";
import { payloadTotalError } from "@/lib/roster/shape-editor-model";
import { Card, CardContent } from "@/components/ui/card";
import { NumberInput } from "@/components/ui/number-input";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useRegistrationFormSection } from "../useRegistrationFormSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

export default function RosterSettingsPage() {
  return (
    <SettingsSectionPage
      section="roster"
      description="How many players of each role a team of this tournament fields, and how deep its bench may go."
    >
      {({ tournament, tournamentId, canUpdateTournament, canTeamCreate }) => (
        <RosterForm
          tournament={tournament}
          tournamentId={tournamentId}
          disabled={!canUpdateTournament}
          benchDisabled={!canTeamCreate}
        />
      )}
    </SettingsSectionPage>
  );
}

function RosterForm({
  tournament,
  tournamentId,
  disabled,
  benchDisabled
}: Readonly<{
  tournament: Tournament;
  tournamentId: number;
  disabled: boolean;
  benchDisabled: boolean;
}>) {
  const t = useTranslations("registrationFormAdmin.page");
  const ids = useId();
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "roster"
  );
  // The bench is the second number of a squad, so it belongs beside the starter
  // slots -- but it is stored on the registration form, not the tournament. Two
  // endpoints, ONE save bar: a screen with two "Save" buttons makes the reader
  // guess which one owns the field they just edited.
  const bench = useRegistrationFormSection(tournamentId);
  // Substitutes only exist where captains register a roster; on balancer or
  // draft formation there is no team to sit anyone out of.
  const hasBench = tournament.team_formation === "registration";

  // The server rejects an out-of-range total with a 422. The editor already
  // says which way it is wrong; the save bar only has to refuse to send it.
  const totalError = payloadTotalError(form.roster_slots_json);
  const benchDirty = hasBench && bench.dirty;

  return (
    <>
      <RosterShapeEditor
        value={form.roster_slots_json}
        effective={tournament.roster_shape}
        locked={tournament.roster_locked_by_draft === true}
        disabled={disabled}
        onChange={(next) => patch({ roster_slots_json: next })}
      />

      {hasBench ? (
        <Card>
          <CardContent className="pt-6">
            <SettingGroup title={t("bench.title")} description={t("bench.description")}>
              <SettingRow
                htmlFor={`${ids}-max-substitutes`}
                label={t("team.maxSubstitutes")}
                hint={t("team.maxSubstitutesHint")}
              >
                <NumberInput
                  id={`${ids}-max-substitutes`}
                  integer
                  min={0}
                  value={bench.value.max_substitutes ?? 0}
                  disabled={benchDisabled}
                  onValueChange={(next) => bench.patch({ max_substitutes: next ?? 0 })}
                  aria-label={t("team.maxSubstitutesAria")}
                  className="h-8 w-24"
                />
              </SettingRow>
            </SettingGroup>
          </CardContent>
        </Card>
      ) : null}

      <SaveBar
        dirty={dirty || benchDirty}
        summary={
          totalError
            ? "The roster total above is out of range"
            : [dirty ? summary : null, benchDirty ? bench.summary : null]
                .filter(Boolean)
                .join(" · ")
        }
        saving={saving || bench.saving}
        onDiscard={() => {
          discard();
          bench.discard();
        }}
        onSave={() => {
          if (totalError) return;
          if (dirty) save();
          if (benchDirty) bench.save();
        }}
      />
    </>
  );
}
