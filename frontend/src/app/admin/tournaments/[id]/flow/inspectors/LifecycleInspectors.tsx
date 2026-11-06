"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import RegistrationsTable from "@/components/balancer/registrations/RegistrationsTable";
import { Button } from "@/components/ui/button";
import { FlowNodeControls } from "@/components/tournaments/FlowNodeControls";
import { usePermissions } from "@/hooks/usePermissions";
import type { DraftNode } from "@/lib/flow/flowDraft";
import { poolRegistrationNodeId } from "@/lib/tournament/flow-nodes";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

import { StageEditor } from "../../bracket/components/StageEditor";
import { useBracketTabData } from "../../bracket/useBracketTabData";
import { DraftSessionDashboard } from "../../components/DraftSessionDashboard";
import { RegistrationNodeSettingsForm } from "../../settings/registration/RegistrationNodeSettingsForm";
import { NodeScheduleEditor } from "../../settings/schedule/NodeScheduleEditor";
import { SelectField } from "./fields";

type SavedProps = Readonly<{ tournamentId: number; tournament: Tournament; saved: TournamentFlowNode; readOnly: boolean }>;

export function RegistrationInspector({ tournamentId, tournament, saved, readOnly }: SavedProps) {
  return (
    <div className="space-y-4">
      <FlowNodeControls tournament={tournament} node={saved} canUpdate={!readOnly} />
      <RegistrationNodeSettingsForm key={saved.id} tournament={tournament} node={saved} />
      <NodeScheduleEditor key={saved.id} tournamentId={tournamentId} node={saved} disabled={readOnly} />
      <RegistrationsTable tournamentId={tournamentId} registrationNodeId={saved.id} />
    </div>
  );
}

const MODES = ["balancer", "draft", "registered", "manual"] as const;

/** The mode edits the draft config (a saved node may change it only while `draft`); the screens below are the saved node's. */
export function FormationMode({
  node,
  readOnly,
  onChange
}: Readonly<{ node: DraftNode; readOnly: boolean; onChange: (patch: Pick<DraftNode, "config">) => void }>) {
  const t = useTranslations("adminTournament.flow.inspector");
  return (
    <SelectField
      label={t("mode")}
      value={String(node.config.mode ?? "manual")}
      options={MODES.map((mode) => [mode, t(`modes.${mode}`)] as const)}
      disabled={readOnly || node.status !== "draft"}
      onChange={(mode) => onChange({ config: { ...node.config, mode } })}
    />
  );
}

export function FormationInspector({
  tournamentId,
  tournament,
  saved,
  readOnly,
  mode
}: SavedProps & Readonly<{ mode: string }>) {
  const t = useTranslations("adminTournament.flow.inspector");
  const { canAccessPermission } = usePermissions();
  const registrationNodeId = poolRegistrationNodeId(saved);
  const link = (href: string, label: string) => (
    <Button asChild variant="outline">
      <Link href={href}>{label}</Link>
    </Button>
  );

  return (
    <div className="space-y-4">
      <FlowNodeControls tournament={tournament} node={saved} canUpdate={!readOnly} />
      {mode === "draft" && registrationNodeId !== null ? (
        <DraftSessionDashboard
          tournamentId={tournamentId}
          formationNodeId={saved.id}
          registrationNodeId={registrationNodeId}
          canManage={canAccessPermission("team.create", tournament.workspace_id)}
        />
      ) : null}
      {mode === "balancer" ? link(`/balancer?tournament=${tournamentId}&node=${saved.id}`, t("openBalancer")) : null}
      {mode === "registered" ? link(`/admin/tournaments/${tournamentId}/registration/teams`, t("openRegisteredTeams")) : null}
      {mode === "manual" ? link(`/admin/tournaments/${tournamentId}/teams/roster`, t("openRoster")) : null}
    </div>
  );
}

export function StageInspector({
  tournamentId,
  node,
  onClose
}: Readonly<{ tournamentId: number; node: DraftNode; onClose: () => void }>) {
  const queryClient = useQueryClient();
  const { isSuperuser } = usePermissions();
  const { orderedStages, progressByStageId, tournamentQuery, teams, isTeamsLoading } = useBracketTabData(tournamentId);
  const stage = orderedStages.find((s) => s.id === node.stageId);
  if (!stage) return null;

  return (
    <StageEditor
      key={stage.id}
      stage={stage}
      stages={orderedStages}
      tournament={tournamentQuery.data}
      teams={teams}
      isTeamsLoading={isTeamsLoading}
      progress={progressByStageId.get(stage.id)}
      isSuperuser={isSuperuser}
      encountersHref={`/admin/tournaments/${tournamentId}/matches/encounters?stage=${stage.id}`}
      onChanged={() => void invalidateTournamentWorkspace(queryClient, tournamentId)}
      onSelect={(id) => id === null && onClose()}
    />
  );
}
