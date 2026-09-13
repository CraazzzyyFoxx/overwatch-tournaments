"use client";

import { useId } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/admin/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/admin/kit/SettingRow";
import { useRequirementDescription } from "@/components/admin/subscriptions/useRequirementDescription";
import { Card, CardContent } from "@/components/ui/card";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SettingsSectionPage } from "../SettingsSection";
import { useRegistrationFormSection } from "../useRegistrationFormSection";

/**
 * Every rule that refuses an entry, on one screen.
 *
 * They used to sit in three groups of the questionnaire builder — profile,
 * subscription, and a "Registered teams" group whose description had to list
 * three unrelated things — so "why was this player not admitted" could only be
 * answered by reading the page top to bottom.
 */
export default function AdmissionSettingsPage() {
  return (
    <SettingsSectionPage
      section="admission"
      description="Every rule that can refuse an entry: profile, subscription, and the team-level checks run before export."
    >
      {({ tournament, tournamentId, canTeamCreate }) => (
        <AdmissionForm
          tournamentId={tournamentId}
          teamRegistration={tournament.team_formation === "registration"}
          disabled={!canTeamCreate}
        />
      )}
    </SettingsSectionPage>
  );
}

function AdmissionForm({
  tournamentId,
  teamRegistration,
  disabled
}: Readonly<{ tournamentId: number; teamRegistration: boolean; disabled: boolean }>) {
  const t = useTranslations("registrationFormAdmin.page");
  const ids = useId();
  const { value, saved, patch, dirty, summary, saving, save, discard } =
    useRegistrationFormSection(tournamentId);

  // Read-only: the rule lives on the workspace and the server projects it onto
  // the form, so this page can state what the toggle enforces without offering
  // to edit it here.
  const resolvedRequirement = useRequirementDescription(saved?.subscription_requirement_json);

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          <SettingGroup title={t("admission.title")}>
            <SettingRow
              htmlFor={`${ids}-open-profile`}
              label={t("admission.requireOpenProfile")}
              hint={t("admission.hint")}
            >
              <Switch
                id={`${ids}-open-profile`}
                checked={value.require_open_profile ?? false}
                disabled={disabled}
                onCheckedChange={(next) => patch({ require_open_profile: next })}
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-scope`} label={t("admission.scope")}>
              <Select
                value={value.open_profile_scope ?? "main"}
                disabled={disabled || !value.require_open_profile}
                onValueChange={(next) =>
                  patch({ open_profile_scope: next as "main" | "all" })
                }
              >
                <SelectTrigger
                  id={`${ids}-scope`}
                  // Sized from content, not a pixel width: the Russian option
                  // labels are longer and a fixed 230px clipped them.
                  className="h-8 w-fit min-w-[230px] max-w-full text-sm"
                  aria-label={t("admission.scopeAria")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="main">{t("admission.scopeMain")}</SelectItem>
                  <SelectItem value="all">{t("admission.scopeAll")}</SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("subscription.title")} description={t("subscription.hint")}>
            <SettingRow
              htmlFor={`${ids}-subscription`}
              label={t("subscription.require")}
              hint={
                <>
                  {/* The workspace rule reaches this page as a projection ON the
                      form, so `resolvedRequirement === ""` means two different
                      things: the workspace has no rule, or there is no form to
                      read one from (the row is created lazily on first save).
                      Only the first licenses the "enforces nothing" claim. */}
                  {saved === null
                    ? t("subscription.resolvedUnknown")
                    : resolvedRequirement
                      ? t("subscription.resolved", { rule: resolvedRequirement })
                      : t("subscription.resolvedEmpty")}{" "}
                  <Link
                    href="/admin/settings/subscriptions"
                    className="font-medium text-foreground underline underline-offset-4"
                  >
                    {t("subscription.manage")}
                  </Link>
                </>
              }
            >
              <Switch
                id={`${ids}-subscription`}
                checked={value.require_subscription ?? false}
                disabled={disabled}
                onCheckedChange={(next) => patch({ require_subscription: next })}
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-stage`} label={t("subscription.stage")}>
              <Select
                value={value.subscription_stage ?? "check_in"}
                disabled={disabled || !value.require_subscription}
                onValueChange={(next) =>
                  patch({ subscription_stage: next as "registration" | "check_in" })
                }
              >
                <SelectTrigger
                  id={`${ids}-stage`}
                  className="h-8 w-fit min-w-[230px] max-w-full text-sm"
                  aria-label={t("subscription.stageAria")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="check_in">{t("subscription.stageCheckIn")}</SelectItem>
                  <SelectItem value="registration">
                    {t("subscription.stageRegistration")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
            {/* Who the rule is evaluated against. Only a tournament whose teams
                register as teams has a captain who could pay for one. */}
            {teamRegistration ? (
              <SettingRow
                htmlFor={`${ids}-sub-scope`}
                label={t("team.scope")}
                hint={t("team.scopeHint")}
              >
                <Select
                  value={value.subscription_scope ?? "player"}
                  disabled={disabled || !value.require_subscription}
                  onValueChange={(next) =>
                    patch({ subscription_scope: next as "player" | "team" })
                  }
                >
                  <SelectTrigger
                    id={`${ids}-sub-scope`}
                    className="h-8 w-fit min-w-[230px] max-w-full text-sm"
                    aria-label={t("team.scopeAria")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="player">{t("team.scopePlayer")}</SelectItem>
                    <SelectItem value="team">{t("team.scopeTeam")}</SelectItem>
                  </SelectContent>
                </Select>
              </SettingRow>
            ) : null}
          </SettingGroup>

          {/* Structurally empty without registered teams: there is no roster to
              check a rank spread or a duplicate identity across. */}
          {teamRegistration ? (
            <SettingGroup title={t("team.title")} description={t("team.description")}>
              <SettingRow
                htmlFor={`${ids}-rank-min`}
                label={t("team.rankMin")}
                hint={t("team.rankHint")}
              >
                <NumberInput
                  id={`${ids}-rank-min`}
                  integer
                  min={0}
                  value={value.team_rank_min ?? null}
                  disabled={disabled}
                  onValueChange={(next) => patch({ team_rank_min: next })}
                  className="h-8 w-24"
                />
              </SettingRow>
              <SettingRow htmlFor={`${ids}-rank-max`} label={t("team.rankMax")}>
                <NumberInput
                  id={`${ids}-rank-max`}
                  integer
                  min={0}
                  value={value.team_rank_max ?? null}
                  disabled={disabled}
                  onValueChange={(next) => patch({ team_rank_max: next })}
                  className="h-8 w-24"
                />
              </SettingRow>
              <SettingRow htmlFor={`${ids}-rank-spread`} label={t("team.rankSpread")}>
                <NumberInput
                  id={`${ids}-rank-spread`}
                  integer
                  min={0}
                  value={value.team_max_rank_spread ?? null}
                  disabled={disabled}
                  onValueChange={(next) => patch({ team_max_rank_spread: next })}
                  className="h-8 w-24"
                />
              </SettingRow>
              <SettingRow
                htmlFor={`${ids}-unique-id`}
                label={t("team.uniqueIdentity")}
                hint={t("team.uniqueIdentityHint")}
              >
                <Switch
                  id={`${ids}-unique-id`}
                  checked={value.team_unique_identity ?? false}
                  disabled={disabled}
                  onCheckedChange={(next) => patch({ team_unique_identity: next })}
                />
              </SettingRow>
              <SettingRow
                htmlFor={`${ids}-discord-guild`}
                label={t("team.requireDiscordGuild")}
                hint={t("team.requireDiscordGuildHint")}
              >
                <Switch
                  id={`${ids}-discord-guild`}
                  checked={value.team_require_discord_guild ?? false}
                  disabled={disabled}
                  onCheckedChange={(next) => patch({ team_require_discord_guild: next })}
                />
              </SettingRow>
            </SettingGroup>
          ) : null}
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
