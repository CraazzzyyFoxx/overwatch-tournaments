"use client";

import { useId } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import { SaveBar } from "@craazzzyyfoxx/admin-kit/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Switch } from "@/components/ui/switch";
import { PageStateCard } from "@/components/ui/page-state-card";
import { tabFallback } from "../../hubQueries";
import { FlowNodeScope } from "../FlowNodeScope";
import { SettingsSectionPage } from "../SettingsSection";
import { useRegistrationFormSection } from "../useRegistrationFormSection";
import { RegistrationNodeSettingsForm } from "./RegistrationNodeSettingsForm";
import { useUnsavedReporter } from "@/components/kit/SettingsContinuation";

const RegistrationFormBuilder = dynamic(
  () => import("@/components/balancer/form/RegistrationFormBuilder"),
  { loading: () => tabFallback }
);

/**
 * How entries are taken, what the public sees of them, and the questionnaire
 * itself. The builder used to be a Registration sub-tab of its own; it is
 * configuration, so it lives here (`registration/form` redirects to this page).
 *
 * Three editors, three save bars: the intake settings belong to one registration
 * node, the other two write the same full-replace form, and each echoes the
 * other's saved fields. Each bar is sticky only inside its own block, so they
 * never stack. The public-page card shares the intake cards' grid, its bar
 * wrapped with it, so the page reads as one set of cards.
 */
export default function RegistrationSettingsPage() {
  const t = useTranslations("registrationFormAdmin.page");
  return (
    <SettingsSectionPage section="registration">
      {({ tournament, tournamentId, canTeamCreate }) => (
        <>
          <div>
            <FlowNodeScope
              kind="registration"
              tournament={tournament}
              fallback={
                <SettingsGrid>
                  <PublicPageForm tournamentId={tournamentId} disabled={!canTeamCreate} />
                </SettingsGrid>
              }
            >
              {(node) => (
                <RegistrationNodeSettingsForm tournament={tournament} node={node}>
                  <PublicPageForm tournamentId={tournamentId} disabled={!canTeamCreate} />
                </RegistrationNodeSettingsForm>
              )}
            </FlowNodeScope>
          </div>
          <section className="flex flex-col gap-3">
            <h2 className={eyebrowClass("muted")}>{t("questionnaire.title")}</h2>
            <RegistrationFormBuilder
              tournamentId={tournamentId}
              identityProvider={tournament.identity_provider}
            />
          </section>
        </>
      )}
    </SettingsSectionPage>
  );
}

function PublicPageForm({
  tournamentId,
  disabled
}: Readonly<{ tournamentId: number; disabled: boolean }>) {
  const reportUnsaved = useUnsavedReporter();
  const t = useTranslations("registrationFormAdmin.page");
  const ids = useId();
  const { value, patch, dirty, summary, saving, save, discard, error, retry } =
    useRegistrationFormSection(tournamentId);

  if (!value) {
    return error ? (
      <PageStateCard
        state="error"
        title={t("loadError.title")}
        description={error.message}
        onAction={retry}
      />
    ) : (
      tabFallback
    );
  }

  return (
    <div>
      <SettingGroup id="display" title={t("display.title")} description={t("display.description")}>
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

      <SaveBar
        onDirtyChange={reportUnsaved}
        dirty={dirty}
        summary={summary}
        saving={saving}
        onDiscard={discard}
        onSave={save}
      />
    </div>
  );
}
