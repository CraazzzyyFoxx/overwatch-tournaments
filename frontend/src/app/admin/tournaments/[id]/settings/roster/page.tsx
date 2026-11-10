"use client";

import { useId, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { TeamFormatEditor } from "@/components/roster-shape/TeamFormatEditor";
import { teamFormatPayload, teamFormatErrors, teamFormatsEqual, type TeamFormatWrite } from "@/lib/roster/team-format";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useScopedSettingsForm } from "@/components/kit/useScopedSettingsForm";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { hasTeamIntake } from "@/lib/tournament/flow-nodes";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import adminService from "@/services/admin.service";
import { NumberInput } from "@/components/ui/number-input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { tabFallback } from "../../hubQueries";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { FlowNodeScope } from "../FlowNodeScope";
import { useRegistrationNodeConfig } from "../useRegistrationNodeConfig";
import type { TournamentFlowNode } from "@/types/flow.types";

export default function RosterSettingsPage() {
  return (
    <SettingsSectionPage section="roster">
      {({ tournament, tournamentId, canUpdateTournament }) => {
        const form = (node: TournamentFlowNode | null) => (
          <RosterForm
            key={`${tournament.workspace_id}:${tournament.discipline}:${tournamentId}`}
            tournament={tournament}
            tournamentId={tournamentId}
            node={node}
            disabled={!canUpdateTournament}
          />
        );
        return hasTeamIntake(tournament) ? (
          <FlowNodeScope kind="registration" tournament={tournament} fallback={form(null)}>
            {form}
          </FlowNodeScope>
        ) : (
          form(null)
        );
      }}
    </SettingsSectionPage>
  );
}

function RosterForm({
  tournament,
  tournamentId,
  node,
  disabled
}: Readonly<{
  tournament: Tournament;
  tournamentId: number;
  /** The registration node holding the bench size; null where there is no bench. */
  node: TournamentFlowNode | null;
  disabled: boolean;
}>) {
  const t = useTranslations("registrationFormAdmin.page");
  const formatT = useTranslations("common.roleOntology");
  const ids = useId();
  const client = useQueryClient();
  const owner = { id: tournamentId, workspaceId: tournament.workspace_id, discipline: tournament.discipline };
  const key = adminQueryKeys.tournamentTeamFormat(owner.id, owner.workspaceId, owner.discipline);
  const formatQuery = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => adminService.getTournamentTeamFormat(owner.id, owner.workspaceId, signal)
  });
  const metadata = useDisciplineMetadata(owner.workspaceId, owner.discipline);
  const baseline = useMemo(() => formatQuery.data ? teamFormatPayload(formatQuery.data) : null, [formatQuery.data]);
  const { form, patch, dirty, summary, saving, save, discard, error } = useScopedSettingsForm<TeamFormatWrite, TeamFormatWrite>({
    baseline,
    toPayload: form => teamFormatPayload(form),
    countChanges: (payload, _form, base) => teamFormatsEqual(payload, base) ? 0 : 1,
    submit: payload => {
      if (!metadata.data || teamFormatErrors(payload, metadata.data).length || disabled || tournament.roster_locked_by_draft) {
        return Promise.reject(new Error(formatT("invalidFormat")));
      }
      return adminService.updateTournamentTeamFormat(owner.id, owner.workspaceId, payload);
    },
    onSaved: () => {
      void client.invalidateQueries({ queryKey: key });
      void invalidateTournamentWorkspace(client, owner.id);
    }
  });
  // The bench is the second number of a squad, so it belongs beside the starter
  // slots -- but it is stored in the registration node's config, not the tournament. Two
  // endpoints, ONE save bar: a screen with two "Save" buttons makes the reader
  // guess which one owns the field they just edited.
  const bench = useRegistrationNodeConfig(tournamentId, node);
  // Substitutes only exist where captains register a roster; on balancer or
  // draft formation there is no team to sit anyone out of.
  const hasBench = node !== null;

  const errors = form && metadata.data ? teamFormatErrors(form, metadata.data) : ["metadata"];
  const totalError = errors.length > 0;
  const benchDirty = bench.dirty;

  return (
    <>
      {formatQuery.isError || metadata.isError ? (
        <PageStateCard state="error" title={formatT("loadError")} onAction={() => { void formatQuery.refetch(); void metadata.refetch(); }} />
      ) : form && metadata.data ? (
        <TeamFormatEditor value={form} ontology={metadata.data} presets={metadata.data.team_format_presets.map(teamFormatPayload)}
          locked={tournament.roster_locked_by_draft === true} disabled={disabled || saving} showSubstitutes={hasBench} onChange={patch} />
      ) : tabFallback}
      {form && totalError && <p role="alert" className="text-sm text-destructive">{formatT("invalidFormat")}</p>}

      {hasBench && bench.form ? (
        <SettingsGrid>
          <SettingGroup id="bench" title={t("bench.title")} description={t("bench.description")}>
            <SettingRow
              htmlFor={`${ids}-max-substitutes`}
              label={t("team.maxSubstitutes")}
              hint={t("team.maxSubstitutesHint")}
            >
              <NumberInput
                id={`${ids}-max-substitutes`}
                integer
                min={0}
                value={bench.form.max_substitutes}
                disabled={disabled}
                onValueChange={(next) => bench.patch({ max_substitutes: next ?? 0 })}
                aria-label={t("team.maxSubstitutesAria")}
                size="sm"
                className="w-24"
              />
            </SettingRow>
          </SettingGroup>
        </SettingsGrid>
      ) : null}

      <SaveBar
        dirty={dirty || benchDirty}
        summary={
          totalError
            ? formatT("invalidFormat")
            : [dirty ? summary : null, benchDirty ? bench.summary : null]
                .filter(Boolean)
                .join(" · ")
        }
        error={error ?? bench.error}
        saving={saving || bench.saving}
        onDiscard={() => {
          discard();
          bench.discard();
        }}
        onSave={() => {
          if (totalError) return;
          if (dirty && !disabled && !tournament.roster_locked_by_draft) save();
          if (benchDirty && !disabled) bench.save();
        }}
      />
    </>
  );
}
