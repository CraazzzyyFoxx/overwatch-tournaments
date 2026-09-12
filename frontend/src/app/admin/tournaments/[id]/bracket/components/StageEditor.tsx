"use client";

import { Fragment, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import {
  GitMerge,
  Loader2,
  MoreHorizontal,
  PlayCircle,
  Shuffle,
  Trash2,
  Undo2,
  Wand2,
  Workflow,
  Link2,
  Zap
} from "lucide-react";

import { AdminTabs, type AdminTabItem } from "@/components/admin/kit/AdminTabs";
import { ConfirmDialog, type ConfirmIntent } from "@/components/admin/kit/ConfirmDialog";
import { EntityHubHeader } from "@/components/admin/kit/EntityHubHeader";
import { SaveBar } from "@/components/admin/kit/SaveBar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Stage, StageItem, Tournament } from "@/types/tournament.types";
import type { Team } from "@/types/team.types";

import {
  BRACKET_STAGE_TYPES,
  getDefaultMergedStageName,
  getStageStatus,
  getStageStatusTone,
  GROUP_STAGE_TYPES,
  isMergeableGroupStage,
  normalizeMaxRounds,
  projectStage,
  STAGE_TYPE_LABELS,
  type StageProgress
} from "../projection";
import {
  buildStageUpdatePayload,
  stageFormChanges,
  stageFormFromStage,
  type StageForm
} from "../stageForm";
import { RoundScheduleSection } from "./RoundScheduleSection";
import { StageItemsSection } from "./StageItemsSection";
import {
  BestOfSection,
  GeneralSection,
  SeedingSection,
  TiebreakersSection
} from "./StageSettingsSections";

export const BRACKET_SECTIONS = [
  "general",
  "seeding",
  "tiebreakers",
  "best-of",
  "schedule",
  "items"
] as const;
export type BracketSection = (typeof BRACKET_SECTIONS)[number];

const SECTION_LABELS: Record<BracketSection, string> = {
  general: "General",
  seeding: "Seeding",
  tiebreakers: "Tiebreakers",
  "best-of": "Best-of",
  schedule: "Round schedule",
  items: "Items"
};

/** Every confirm-guarded stage operation, and what the dialog says about it. */
type PendingOp =
  | { kind: "delete-stage" }
  | { kind: "delete-item"; item: StageItem }
  | { kind: "seed" }
  | { kind: "merge" }
  | { kind: "force-activate" }
  | { kind: "deactivate" }
  | { kind: "regenerate" };

interface StageEditorProps {
  stage: Stage;
  stages: Stage[];
  tournament: Tournament | undefined;
  teams: Team[];
  isTeamsLoading: boolean;
  progress: StageProgress | undefined;
  isSuperuser: boolean;
  /** `Matches › Encounters` scoped to this stage. */
  encountersHref: string;
  onChanged: () => void;
  /** After a delete or a merge the selected stage is gone. */
  onSelect: (stageId: number | null) => void;
}

/**
 * The detail column of the Bracket tab: one stage, five sections, one save.
 *
 * The pre-redesign screen put all of this behind an `Advanced` disclosure and
 * spread seven separate delete-confirmation dialogs around it. Here the
 * sections are routed (`?section=`), the drafts are one object, and every
 * destructive operation goes through the single `ConfirmDialog` below with a
 * swapped `intent`.
 *
 * Mount with `key={stage.id}`: the drafts are per-stage, and remounting is how
 * they reset when the selection changes.
 */
export function StageEditor({
  stage,
  stages,
  tournament,
  teams,
  isTeamsLoading,
  progress,
  isSuperuser,
  encountersHref,
  onChanged,
  onSelect
}: Readonly<StageEditorProps>) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [form, setForm] = useState<StageForm>(() => stageFormFromStage(stage));
  const [pendingOp, setPendingOp] = useState<PendingOp | null>(null);

  const hasEncounters = (progress?.total ?? 0) > 0;
  const changes = stageFormChanges(stage, form);
  const projection = useMemo(
    () =>
      projectStage({
        stage,
        stages,
        stageType: form.stageType,
        splitLowerBracket: form.stageType === "double_elimination" && form.splitLowerBracket,
        maxRounds: normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5),
        bestOf: form.bestOf
      }),
    [stage, stages, form.stageType, form.splitLowerBracket, form.maxRounds, form.bestOf]
  );

  const mergeCandidates = isMergeableGroupStage(stage)
    ? stages.filter(
        (candidate) =>
          candidate.id !== stage.id &&
          candidate.stage_type === stage.stage_type &&
          isMergeableGroupStage(candidate)
      )
    : [];
  const mergedName = getDefaultMergedStageName(stage);

  const sectionAllowed: Record<BracketSection, boolean> = {
    general: true,
    seeding: true,
    // Standings presets, scoring and tiebreakers only rank a group stage.
    tiebreakers: GROUP_STAGE_TYPES.includes(form.stageType),
    "best-of": true,
    schedule: true,
    items: true
  };
  const requested = searchParams?.get("section") ?? "";
  const section: BracketSection = (BRACKET_SECTIONS as readonly string[]).includes(requested)
    ? (requested as BracketSection)
    : "general";
  const activeSection = sectionAllowed[section] ? section : "general";

  const sectionHref = (key: BracketSection) => {
    const next = new URLSearchParams(searchParams?.toString() ?? "");
    next.set("stage", String(stage.id));
    next.set("section", key);
    return `${pathname}?${next.toString()}`;
  };

  const updateMutation = useMutation({
    mutationFn: () => adminService.updateStage(stage.id, buildStageUpdatePayload(stage, form)),
    onSuccess: (saved) => {
      setForm(stageFormFromStage(saved));
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: "Could not save this stage" })
  });

  const activateMutation = useMutation({
    mutationFn: () => adminService.activateStage(stage.id),
    onSuccess: () => onChanged()
  });

  const deactivateMutation = useMutation({
    mutationFn: () => adminService.deactivateStage(stage.id),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
      notify.success("Stage reverted to draft");
    },
    onError: (error) => notify.apiError(error, { title: "Could not revert this stage to draft" })
  });

  const generateMutation = useMutation({
    mutationFn: () => adminService.generateBracket(stage.id),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: "Could not generate the bracket" })
  });

  const applyBestOfMutation = useMutation({
    mutationFn: () => adminService.applyStageBestOf(stage.id),
    onSuccess: ({ updated }) => {
      notify.success(`Updated best-of on ${updated} match${updated === 1 ? "" : "es"}`);
      onChanged();
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not apply best-of to existing matches" })
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteStage(stage.id),
    onSuccess: () => {
      setPendingOp(null);
      onSelect(null);
      onChanged();
    }
  });

  const mergeMutation = useMutation({
    mutationFn: () =>
      adminService.mergeGroupStages(stage.id, {
        source_stage_ids: mergeCandidates.map((candidate) => candidate.id),
        target_name: mergedName
      }),
    onSuccess: (merged) => {
      setPendingOp(null);
      onSelect(merged.id);
      onChanged();
    }
  });

  const autoWireMutation = useMutation({
    mutationFn: () => adminService.autoWireStage(stage.id),
    onSuccess: () => {
      onChanged();
      notify.success("Auto-wired playoff seeds from the group stage");
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not auto-wire this stage from groups" })
  });

  const activateAndGenerateMutation = useMutation({
    mutationFn: (force?: boolean) =>
      adminService.activateAndGenerateStage(stage.id, force ? { force: true } : undefined),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error, force) => {
      // The server refuses while an upstream stage is unfinished; that refusal
      // is the prompt for the force confirmation, not an error toast.
      const detail =
        error && typeof error === "object" && "detail" in error ? error.detail : null;
      const upstreamPending =
        typeof detail === "object" &&
        detail !== null &&
        "code" in detail &&
        typeof detail.code === "string" &&
        detail.code === "upstream_stages_not_completed";
      if (upstreamPending && !force) {
        setPendingOp({ kind: "force-activate" });
        return;
      }
      setPendingOp(null);
      notify.apiError(error, { title: "Could not activate and generate this stage" });
    }
  });

  const seedMutation = useMutation({
    mutationFn: () =>
      adminService.seedTeams(stage.id, {
        team_ids: teams.map((team) => team.id),
        mode: "snake_sr"
      }),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: "Could not seed teams into this stage" })
  });

  const deleteItemMutation = useMutation({
    mutationFn: (stageItemId: number) => adminService.deleteStageItem(stageItemId),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: "Could not delete this structure item" })
  });

  const isBracket = BRACKET_STAGE_TYPES.includes(stage.stage_type);
  const canSeed =
    GROUP_STAGE_TYPES.includes(stage.stage_type) && teams.length > 0 && stage.items.length > 0;
  const canDeactivate = (stage.is_active || stage.is_published) && !stage.is_completed;

  const intent = pendingOp
    ? INTENTS[pendingOp.kind](stage, pendingOp, {
        teamCount: teams.length,
        mergedName,
        mergeCandidates
      })
    : NEUTRAL_INTENT;

  const pendingByOp: Record<PendingOp["kind"], boolean> = {
    "delete-stage": deleteMutation.isPending,
    "delete-item": deleteItemMutation.isPending,
    seed: seedMutation.isPending,
    merge: mergeMutation.isPending,
    "force-activate": activateAndGenerateMutation.isPending,
    deactivate: deactivateMutation.isPending,
    regenerate: generateMutation.isPending
  };
  const opPending = pendingOp ? pendingByOp[pendingOp.kind] : false;

  const runPendingOp = () => {
    if (!pendingOp) return;
    if (pendingOp.kind === "delete-stage") deleteMutation.mutate();
    else if (pendingOp.kind === "delete-item") deleteItemMutation.mutate(pendingOp.item.id);
    else if (pendingOp.kind === "seed") seedMutation.mutate();
    else if (pendingOp.kind === "merge") mergeMutation.mutate();
    else if (pendingOp.kind === "force-activate") activateAndGenerateMutation.mutate(true);
    else if (pendingOp.kind === "deactivate") deactivateMutation.mutate();
    else generateMutation.mutate();
  };

  const tabs: AdminTabItem[] = BRACKET_SECTIONS.map((key) => ({
    key,
    label: SECTION_LABELS[key],
    href: sectionHref(key),
    badge: key === "items" ? stage.items.length || undefined : undefined,
    hidden: !sectionAllowed[key]
  }));

  return (
    <div className="min-w-0 rounded-xl border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <EntityHubHeader
          level={2}
          title={stage.name}
          status={{
            label: getStageStatus(stage, hasEncounters),
            tone: getStageStatusTone(stage, hasEncounters)
          }}
          meta={[
            STAGE_TYPE_LABELS[stage.stage_type],
            <span key="slots" className="tabular-nums">
              {projection.assigned}/{projection.slots} slots
            </span>,
            hasEncounters ? (
              <span key="matches" className="tabular-nums">
                {progress?.completed}/{progress?.total} matches
              </span>
            ) : null,
            // Captain visibility used to sit in the General form under a second
            // "Status" label, beside a second status badge. It is a fact about
            // the stage, so it lives with the other facts up here.
            stage.is_published ? "Published to captains" : "Not visible to captains",
            stage.challonge_slug ? (
              <a
                key="challonge"
                className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                href={`https://challonge.com/${stage.challonge_slug}`}
                target="_blank"
                rel="noreferrer"
              >
                <Link2 className="size-3" aria-hidden />
                Challonge
              </a>
            ) : null
          ]}
          actions={
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={generateMutation.isPending}
                onClick={() => {
                  if (hasEncounters) setPendingOp({ kind: "regenerate" });
                  else generateMutation.mutate();
                }}
                title="Generates the bracket as a preview without activating the stage — captains cannot report or veto until it is activated. With no teams seeded yet, a playoff is built from the group stage's advancing count and filled in once the groups finish."
              >
                {generateMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Wand2 className="size-4" aria-hidden />
                )}
                {hasEncounters ? "Regenerate" : "Generate bracket"}
              </Button>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon" variant="ghost" aria-label={`Actions for ${stage.name}`}>
                    <MoreHorizontal className="size-4" aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {stage.is_active ? null : (
                    <DropdownMenuItem
                      disabled={activateMutation.isPending}
                      onSelect={() => activateMutation.mutate()}
                    >
                      <PlayCircle className="size-4" aria-hidden />
                      Activate stage
                    </DropdownMenuItem>
                  )}
                  {isBracket ? (
                    <DropdownMenuItem
                      disabled={activateAndGenerateMutation.isPending}
                      onSelect={() => activateAndGenerateMutation.mutate(undefined)}
                    >
                      <Zap className="size-4" aria-hidden />
                      Activate &amp; generate
                    </DropdownMenuItem>
                  ) : null}
                  {isBracket ? (
                    <DropdownMenuItem
                      disabled={autoWireMutation.isPending}
                      onSelect={() => autoWireMutation.mutate()}
                    >
                      <Workflow className="size-4" aria-hidden />
                      Auto-wire from groups
                    </DropdownMenuItem>
                  ) : null}
                  {canSeed ? (
                    <DropdownMenuItem onSelect={() => setPendingOp({ kind: "seed" })}>
                      <Shuffle className="size-4" aria-hidden />
                      Seed by SR
                    </DropdownMenuItem>
                  ) : null}
                  {mergeCandidates.length > 0 ? (
                    <DropdownMenuItem onSelect={() => setPendingOp({ kind: "merge" })}>
                      <GitMerge className="size-4" aria-hidden />
                      Merge groups
                    </DropdownMenuItem>
                  ) : null}
                  {canDeactivate ? (
                    <DropdownMenuItem onSelect={() => setPendingOp({ kind: "deactivate" })}>
                      <Undo2 className="size-4" aria-hidden />
                      Revert to draft
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem
                    className="text-danger focus:text-danger"
                    onSelect={() => setPendingOp({ kind: "delete-stage" })}
                  >
                    <Trash2 className="size-4" aria-hidden />
                    Delete stage
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          }
        />
      </div>

      <div className="border-b border-border px-4 py-2">
        <AdminTabs
          items={tabs}
          activeKey={activeSection}
          level={2}
          ariaLabel={`${stage.name} sections`}
        />
      </div>

      <div className="p-4">
        {activeSection === "general" ? (
          <GeneralSection
            stage={stage}
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
            isSuperuser={isSuperuser}
            projection={projection}
            teams={teams}
          />
        ) : null}

        {activeSection === "seeding" ? (
          <SeedingSection
            stage={stage}
            stages={stages}
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
            onChanged={onChanged}
          />
        ) : null}

        {activeSection === "tiebreakers" ? (
          <TiebreakersSection
            stage={stage}
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
            winPointsDefault={tournament?.win_points ?? 1}
            drawPointsDefault={tournament?.draw_points ?? 0.5}
            lossPointsDefault={tournament?.loss_points ?? 0}
          />
        ) : null}

        {activeSection === "best-of" ? (
          <BestOfSection
            stage={stage}
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
            bracketTeamCount={projection.bracketTeams.count}
            onApplyToExisting={() => applyBestOfMutation.mutate()}
            applying={applyBestOfMutation.isPending}
          />
        ) : null}

        {activeSection === "schedule" ? (
          <RoundScheduleSection
            stage={stage}
            bracketTeamCount={projection.bracketTeams.count}
            onChanged={onChanged}
          />
        ) : null}

        {activeSection === "items" ? (
          <StageItemsSection
            stage={stage}
            stages={stages}
            teams={teams}
            isTeamsLoading={isTeamsLoading}
            progress={progress}
            encountersHref={encountersHref}
            onChanged={onChanged}
            onRequestDeleteItem={(item) => setPendingOp({ kind: "delete-item", item })}
          />
        ) : null}

        <SaveBar
          dirty={changes.length > 0}
          summary={
            <Fragment>
              Unsaved changes: <span className="text-foreground">{changes.join(", ")}</span>
            </Fragment>
          }
          onDiscard={() => setForm(stageFormFromStage(stage))}
          onSave={() => updateMutation.mutate()}
          saving={updateMutation.isPending}
          // The five sections above are `?section=` links of THIS form, so the
          // anchor guard would demand a discard just to look at another one.
          // The stage list beside it is buttons, which the guard never saw.
          guardNavigation={false}
        />
      </div>

      <ConfirmDialog
        open={pendingOp !== null}
        onOpenChange={(open) => {
          if (!open) setPendingOp(null);
        }}
        intent={intent}
        onConfirm={runPendingOp}
        pending={opPending}
      />
    </div>
  );
}

const NEUTRAL_INTENT: ConfirmIntent = {
  title: "",
  description: "",
  confirmLabel: "Confirm",
  tone: "neutral"
};

/**
 * The seven confirmations of the old screen, as intents of one dialog. The
 * copy is carried over verbatim: it is the only place that explains what each
 * operation does to already-generated matches.
 */
const INTENTS: Record<
  PendingOp["kind"],
  (
    stage: Stage,
    op: PendingOp,
    context: { teamCount: number; mergedName: string; mergeCandidates: Stage[] }
  ) => ConfirmIntent
> = {
  "delete-stage": (stage) => ({
    title: "Delete stage",
    description: `Delete "${stage.name}"? This removes its structure and generated bracket data.`,
    confirmLabel: "Delete stage",
    tone: "danger",
    cascade: ["Stage structure items", "Team input slots", "Generated stage matches"]
  }),
  "delete-item": (_stage, op) => {
    const item = op.kind === "delete-item" ? op.item : null;
    return {
      title: "Delete structure item",
      description: `Delete "${item?.name ?? ""}"? This removes its team slots and generated matches.`,
      confirmLabel: "Delete item",
      tone: "danger",
      cascade: [
        "Team input slots",
        "Generated matches for this group/lane",
        "Standings for this group/lane"
      ]
    };
  },
  seed: (stage, _op, { teamCount }) => ({
    title: "Reseed stage from SR",
    description: `Distribute ${teamCount} teams across ${stage.items.length} group(s) of "${stage.name}" with a snake SR draft. Every manual assignment in this stage is cleared first.`,
    confirmLabel: "Seed teams",
    tone: "warning",
    cascade: ["Manual team assignments in this stage"]
  }),
  merge: (_stage, _op, { mergedName, mergeCandidates }) => ({
    title: "Merge group stages",
    description: `Move the groups, matches and standings of ${mergeCandidates.length} stage(s) into "${mergedName}". The merged stages leave the timeline.`,
    confirmLabel: "Merge stages",
    tone: "warning",
    cascade: mergeCandidates.map((candidate) => `Stage "${candidate.name}"`)
  }),
  "force-activate": (stage) => ({
    title: "Activate before upstream stages finish",
    description: `Upstream stages still have pending encounters. Activating "${stage.name}" now freezes its seeds from standings that can still change.`,
    confirmLabel: "Activate anyway",
    tone: "warning"
  }),
  deactivate: (stage) => ({
    title: "Revert stage to draft",
    description: `Revert "${stage.name}" back to Draft/preview. This only succeeds while every one of its matches is still unplayed — any reported or in-progress match blocks it.`,
    confirmLabel: "Revert to draft",
    tone: "warning"
  }),
  regenerate: (stage) => ({
    title: "Generate bracket again",
    description: `"${stage.name}" already has generated matches. Existing matches are left untouched: for a grouped stage, only groups with no matches yet get a new bracket; for a bracket that is still all TBD, the seeded teams are written into it; otherwise this is blocked until you delete its existing matches.`,
    confirmLabel: "Generate",
    tone: "warning"
  })
};
