"use client";

import { useId } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { StatusPill } from "@/components/kit/StatusPill";
import { Card, CardContent } from "@/components/ui/card";
import { NumberInput } from "@/components/ui/number-input";
import { Switch } from "@/components/ui/switch";
import { SettingsSectionPage } from "../SettingsSection";
import { useRegistrationFormSection } from "../useRegistrationFormSection";

/**
 * How entries are taken, and what the public sees of them.
 *
 * Split out of the questionnaire builder, which mixed this with the admission
 * rules and the fields themselves under six groups on one screen. The rows are
 * translated while the rail around them is not: they came with their messages,
 * and dropping the Russian copy to match an English-only admin shell would be a
 * regression paid by organizers, not by this refactor.
 */
export default function RegistrationSettingsPage() {
  return (
    <SettingsSectionPage
      section="registration"
      description="Whether entries are accepted automatically, and how much of the field the public page shows."
    >
      {({ tournamentId, canTeamCreate }) => (
        <RegistrationForm tournamentId={tournamentId} disabled={!canTeamCreate} />
      )}
    </SettingsSectionPage>
  );
}

function RegistrationForm({
  tournamentId,
  disabled
}: Readonly<{ tournamentId: number; disabled: boolean }>) {
  const t = useTranslations("registrationFormAdmin.page");
  const tStatus = useTranslations("registrationFormAdmin.status");
  const ids = useId();
  const { value, saved, patch, dirty, summary, saving, save, discard } =
    useRegistrationFormSection(tournamentId);

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          <SettingGroup title={tStatus("title")} description={tStatus("description")}>
            {/* Derived, not editable: openness is the REGISTRATION phase-schedule
                window. Shown because this is the screen an organizer opens to ask
                "are we taking entries", and the answer lives one section away. */}
            <SettingRow label={tStatus("acceptLabel")} hint={tStatus("scheduleHint")}>
              <StatusPill tone={saved?.is_open ? "success" : "neutral"}>
                {saved?.is_open ? tStatus("stateOpen") : tStatus("stateClosed")}
              </StatusPill>
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-auto-approve`}
              label={tStatus("autoApproveLabel")}
              hint={tStatus("autoApproveHint")}
            >
              <Switch
                id={`${ids}-auto-approve`}
                checked={value.auto_approve}
                disabled={disabled}
                onCheckedChange={(next) => patch({ auto_approve: next })}
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("display.title")} description={t("display.description")}>
            <SettingRow
              htmlFor={`${ids}-max-participants`}
              label={t("display.maxParticipants")}
              hint={t("display.maxParticipantsHint")}
            >
              <NumberInput
                id={`${ids}-max-participants`}
                integer
                min={0}
                value={value.max_participants ?? null}
                disabled={disabled}
                onValueChange={(next) => patch({ max_participants: next })}
                className="h-8 w-24"
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-hide-registrations`}
              label={t("display.hideRegistrations")}
              hint={t("display.hideRegistrationsHint")}
            >
              <Switch
                id={`${ids}-hide-registrations`}
                checked={value.hide_registrations ?? false}
                disabled={disabled}
                onCheckedChange={(next) => patch({ hide_registrations: next })}
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-show-ranks`}
              label={t("display.showRanks")}
              hint={t("display.hint")}
            >
              <Switch
                id={`${ids}-show-ranks`}
                checked={value.show_ranks ?? false}
                disabled={disabled}
                onCheckedChange={(next) => patch({ show_ranks: next })}
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("questionnaire.title")} description={t("questionnaire.description")}>
            <SettingRow label={t("questionnaire.label")} hint={t("questionnaire.hint")}>
              <Link
                href={`/admin/tournaments/${tournamentId}/registration/form`}
                className="text-sm font-medium text-foreground underline underline-offset-4"
              >
                {t("questionnaire.action")}
              </Link>
            </SettingRow>
          </SettingGroup>
        </CardContent>
      </Card>

      <SaveBar
        dirty={dirty}
        summary={summary}
        saving={saving}
        onDiscard={discard}
        onSave={save}
      />
    </>
  );
}
