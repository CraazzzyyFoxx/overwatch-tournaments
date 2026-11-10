"use client";

import { useId } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { useRequirementDescription } from "@/components/registration/useRequirementDescription";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PageStateCard } from "@/components/ui/page-state-card";
import { registrationIntake } from "@/lib/tournament/flow-nodes";
import { tabFallback } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { FlowNodeScope } from "../FlowNodeScope";
import { useRegistrationFormSection } from "../useRegistrationFormSection";
import { useRegistrationNodeConfig } from "../useRegistrationNodeConfig";
import type { TournamentFlowNode } from "@/types/flow.types";

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
    <SettingsSectionPage section="admission">
      {({ tournament, tournamentId, canTeamCreate, canUpdateTournament }) => (
        <FlowNodeScope kind="registration" tournament={tournament}>
          {(node) => (
            <AdmissionForm
              tournamentId={tournamentId}
              node={node}
              teamRegistration={registrationIntake(tournament, node) === "team"}
              disabled={!canTeamCreate}
              nodeDisabled={!canUpdateTournament}
            />
          )}
        </FlowNodeScope>
      )}
    </SettingsSectionPage>
  );
}

function AdmissionForm({
  tournamentId,
  node,
  teamRegistration,
  disabled,
  nodeDisabled
}: Readonly<{
  tournamentId: number;
  node: TournamentFlowNode;
  teamRegistration: boolean;
  disabled: boolean;
  nodeDisabled: boolean;
}>) {
  const t = useTranslations("registrationFormAdmin.page");
  const ids = useId();
  const { value, saved, patch, dirty, summary, saving, save, discard, error, retry } =
    useRegistrationFormSection(tournamentId);
  // The profile rules are the form's, the subscription and team rules the node's: two endpoints, one save bar.
  const intake = useRegistrationNodeConfig(tournamentId, node);
  const cfg = intake.form;

  // Read-only: the rule lives on the workspace and the server projects it onto
  // the form, so this page can state what the toggle enforces without offering
  // to edit it here.
  const resolvedRequirement = useRequirementDescription(saved?.subscription_requirement_json);

  if (!value || !cfg) {
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
    <>
      <SettingsGrid>
        <SettingGroup id="admission" title={t("admission.title")}>
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
              onValueChange={(next) => patch({ open_profile_scope: next as "main" | "all" })}
            >
              <SelectTrigger
                id={`${ids}-scope`}
                // Sized from content, not a pixel width: the Russian option
                // labels are longer and a fixed 230px clipped them.
                size="sm"
                className="w-fit min-w-[230px] max-w-full"
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

        <SettingGroup id="subscription" title={t("subscription.title")} description={t("subscription.hint")}>
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
              checked={cfg.require_subscription}
              disabled={nodeDisabled}
              onCheckedChange={(next) => intake.patch({ require_subscription: next })}
            />
          </SettingRow>
          <SettingRow htmlFor={`${ids}-stage`} label={t("subscription.stage")}>
            <Select
              value={cfg.subscription_stage}
              disabled={nodeDisabled || !cfg.require_subscription}
              onValueChange={(next) =>
                intake.patch({ subscription_stage: next as "registration" | "check_in" })
              }
            >
              <SelectTrigger
                id={`${ids}-stage`}
                size="sm"
                className="w-fit min-w-[230px] max-w-full"
                aria-label={t("subscription.stageAria")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="check_in">{t("subscription.stageCheckIn")}</SelectItem>
                <SelectItem value="registration">{t("subscription.stageRegistration")}</SelectItem>
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
                value={cfg.subscription_scope}
                disabled={nodeDisabled || !cfg.require_subscription}
                onValueChange={(next) => intake.patch({ subscription_scope: next as "player" | "team" })}
              >
                <SelectTrigger
                  id={`${ids}-sub-scope`}
                  size="sm"
                  className="w-fit min-w-[230px] max-w-full"
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
          <SettingGroup id="team" title={t("team.title")} description={t("team.description")}>
            <SettingRow
              htmlFor={`${ids}-rank-min`}
              label={t("team.rankMin")}
              hint={t("team.rankHint")}
            >
              <NumberInput
                id={`${ids}-rank-min`}
                integer
                min={0}
                value={cfg.team_rank_min}
                disabled={nodeDisabled}
                onValueChange={(next) => intake.patch({ team_rank_min: next })}
                size="sm"
                className="w-24"
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-rank-max`} label={t("team.rankMax")}>
              <NumberInput
                id={`${ids}-rank-max`}
                integer
                min={0}
                value={cfg.team_rank_max}
                disabled={nodeDisabled}
                onValueChange={(next) => intake.patch({ team_rank_max: next })}
                size="sm"
                className="w-24"
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-rank-spread`} label={t("team.rankSpread")}>
              <NumberInput
                id={`${ids}-rank-spread`}
                integer
                min={0}
                value={cfg.team_max_rank_spread}
                disabled={nodeDisabled}
                onValueChange={(next) => intake.patch({ team_max_rank_spread: next })}
                size="sm"
                className="w-24"
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-unique-id`}
              label={t("team.uniqueIdentity")}
              hint={t("team.uniqueIdentityHint")}
            >
              <Switch
                id={`${ids}-unique-id`}
                checked={cfg.team_unique_identity}
                disabled={nodeDisabled}
                onCheckedChange={(next) => intake.patch({ team_unique_identity: next })}
              />
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-discord-guild`}
              label={t("team.requireDiscordGuild")}
              hint={t("team.requireDiscordGuildHint")}
            >
              <Switch
                id={`${ids}-discord-guild`}
                checked={cfg.team_require_discord_guild}
                disabled={nodeDisabled}
                onCheckedChange={(next) => intake.patch({ team_require_discord_guild: next })}
              />
            </SettingRow>
          </SettingGroup>
        ) : null}
      </SettingsGrid>

      <SaveBar
        dirty={dirty || intake.dirty}
        summary={[dirty ? summary : null, intake.dirty ? intake.summary : null].filter(Boolean).join(" · ")}
        error={intake.error}
        saving={saving || intake.saving}
        onDiscard={() => {
          discard();
          intake.discard();
        }}
        onSave={() => {
          if (dirty) save();
          if (intake.dirty && !nodeDisabled) intake.save();
        }}
      />
    </>
  );
}
