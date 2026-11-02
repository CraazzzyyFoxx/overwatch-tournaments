import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import type { ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Stage, StageItem } from "@/types/tournament.types";
import type { Team } from "@/types/team.types";

/** Every confirm-guarded stage operation, and what the dialog says about it. */
type PendingOp =
  | { kind: "delete-stage" }
  | { kind: "delete-item"; item: StageItem }
  | { kind: "remove-input"; inputId: number; label: string }
  | { kind: "seed"; mode?: "captain_rank" }
  | { kind: "merge" }
  | { kind: "force-activate" }
  | { kind: "deactivate" }
  | { kind: "regenerate" };

interface StageOperationsOptions {
  stage: Stage;
  teams: Team[];
  mergeCandidates: Stage[];
  mergedName: string;
  onChanged: () => void;
  /** After a delete or a merge the selected stage is gone. */
  onSelect: (stageId: number | null) => void;
}

/**
 * The stage's one-shot operations and the confirmation pending on one of them:
 * everything `StageEditor`'s single `ConfirmDialog` swaps its `intent` between.
 */
export function useStageOperations({
  stage,
  teams,
  mergeCandidates,
  mergedName,
  onChanged,
  onSelect
}: StageOperationsOptions) {
  const t = useTranslations("adminBracket.editor");
  const tRoot = useTranslations("adminBracket");
  const intentT = t as unknown as (key: string, values?: Record<string, unknown>) => string;
  const intentRootT = tRoot as unknown as (key: string, values?: Record<string, unknown>) => string;
  const [pendingOp, setPendingOp] = useState<PendingOp | null>(null);

  const activateMutation = useMutation({
    mutationFn: () => adminService.activateStage(stage.id),
    onSuccess: () => onChanged()
  });

  const deactivateMutation = useMutation({
    mutationFn: () => adminService.deactivateStage(stage.id),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
      notify.success(t("reverted"));
    },
    onError: (error) => notify.apiError(error, { title: t("revertError") })
  });

  const generateMutation = useMutation({
    mutationFn: () => adminService.generateBracket(stage.id),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: t("generateError") })
  });

  const applyBestOfMutation = useMutation({
    mutationFn: () => adminService.applyStageBestOf(stage.id),
    onSuccess: ({ updated }) => {
      notify.success(t("updatedBestOf", { count: updated }));
      onChanged();
    },
    onError: (error) =>
      notify.apiError(error, { title: t("applyBestOfError") })
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
      notify.success(t("autoWired"));
    },
    onError: (error) =>
      notify.apiError(error, { title: t("autoWireError") })
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
      notify.apiError(error, { title: t("activateError") });
    }
  });

  const seedMutation = useMutation({
    mutationFn: (mode: "snake_sr" | "captain_rank") =>
      adminService.seedTeams(stage.id, {
        team_ids: teams.map((team) => team.id),
        mode
      }),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: t("seedError") })
  });

  const deleteItemMutation = useMutation({
    mutationFn: (stageItemId: number) => adminService.deleteStageItem(stageItemId),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: t("deleteItemError") })
  });

  const removeInputMutation = useMutation({
    mutationFn: (inputId: number) => adminService.deleteStageItemInput(inputId),
    onSuccess: () => {
      setPendingOp(null);
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: t("removeSlotError") })
  });

  const intent = pendingOp
    ? INTENTS(intentT, intentRootT)[pendingOp.kind](stage, pendingOp, {
        teamCount: teams.length,
        mergedName,
        mergeCandidates
      })
    : NEUTRAL_INTENT;

  const pendingByOp: Record<PendingOp["kind"], boolean> = {
    "delete-stage": deleteMutation.isPending,
    "delete-item": deleteItemMutation.isPending,
    "remove-input": removeInputMutation.isPending,
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
    else if (pendingOp.kind === "remove-input") removeInputMutation.mutate(pendingOp.inputId);
    else if (pendingOp.kind === "seed") seedMutation.mutate(pendingOp.mode ?? "snake_sr");
    else if (pendingOp.kind === "merge") mergeMutation.mutate();
    else if (pendingOp.kind === "force-activate") activateAndGenerateMutation.mutate(true);
    else if (pendingOp.kind === "deactivate") deactivateMutation.mutate();
    else generateMutation.mutate();
  };

  return {
    pendingOp,
    setPendingOp,
    intent,
    opPending,
    runPendingOp,
    activateMutation,
    generateMutation,
    applyBestOfMutation,
    autoWireMutation,
    activateAndGenerateMutation
  };
}

const NEUTRAL_INTENT: ConfirmIntent = {
  title: "",
  description: "",
  confirmLabel: "",
  tone: "neutral"
};

/**
 * The seven confirmations of the old screen, as intents of one dialog. The
 * copy is carried over verbatim: it is the only place that explains what each
 * operation does to already-generated matches.
 */
const INTENTS = (t: (key: string, values?: Record<string, unknown>) => string, tRoot: (key: string, values?: Record<string, unknown>) => string): Record<
  PendingOp["kind"],
  (
    stage: Stage,
    op: PendingOp,
    context: { teamCount: number; mergedName: string; mergeCandidates: Stage[] }
  ) => ConfirmIntent
> => ({
  "delete-stage": (stage) => ({
    title: t("deleteStageTitle"),
    description: t("deleteStageDescription", { name: stage.name }),
    confirmLabel: t("deleteStageConfirm"),
    tone: "danger",
    cascade: [tRoot("extra.cascadeStageItems"), tRoot("extra.cascadeTeamSlots"), tRoot("extra.cascadeMatches")]
  }),
  "delete-item": (_stage, op) => {
    const item = op.kind === "delete-item" ? op.item : null;
    return {
      title: t("deleteItemTitle"),
      description: t("deleteItemDescription", { name: item?.name ?? "" }),
      confirmLabel: t("deleteItemConfirm"),
      tone: "danger",
      cascade: [
        tRoot("extra.cascadeTeamSlots"),
        tRoot("extra.cascadeItemMatches"),
        tRoot("extra.cascadeItemStandings")
      ]
    };
  },
  "remove-input": (_stage, op) => ({
    title: t("removeSlotTitle"),
    description: t("removeSlotDescription", { label: op.kind === "remove-input" ? op.label : t("slot") }),
    confirmLabel: t("removeSlotConfirm"),
    tone: "danger",
    cascade: [tRoot("extra.cascadeSeedSlot"), tRoot("extra.cascadeBracketPlace")]
  }),
  seed: (stage, op, { teamCount }) =>
    op.kind === "seed" && op.mode === "captain_rank"
      ? {
          title: t("reseedCaptainTitle"),
          description: t("reseedCaptainDescription", { teams: teamCount, name: stage.name }),
          confirmLabel: t("reseedConfirm"),
          tone: "warning",
          cascade: [tRoot("extra.cascadeManualAssignments")]
        }
      : {
          title: t("reseedTitle"),
          description: t("reseedDescription", { teams: teamCount, groups: stage.items.length, name: stage.name }),
          confirmLabel: t("reseedConfirm"),
          tone: "warning",
          cascade: [tRoot("extra.cascadeManualAssignments")]
        },
  merge: (_stage, _op, { mergedName, mergeCandidates }) => ({
    title: t("mergeTitle"),
    description: t("mergeDescription", { count: mergeCandidates.length, name: mergedName }),
    confirmLabel: t("mergeConfirm"),
    tone: "warning",
    cascade: mergeCandidates.map((candidate) => tRoot("extra.cascadeStage", { name: candidate.name }))
  }),
  "force-activate": (stage) => ({
    title: t("forceActivateTitle"),
    description: t("forceActivateDescription", { name: stage.name }),
    confirmLabel: t("forceActivateConfirm"),
    tone: "warning"
  }),
  deactivate: (stage) => ({
    title: t("revertTitle"),
    description: t("revertDescription", { name: stage.name }),
    confirmLabel: t("revertConfirm"),
    tone: "warning"
  }),
  regenerate: (stage) => ({
    title: t("regenerateTitle"),
    description: t("regenerateDescription", { name: stage.name }),
    confirmLabel: t("regenerateConfirm"),
    tone: "warning"
  })
});
