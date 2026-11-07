"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useFlowErrorMessage } from "@/hooks/useFlowErrorNotifier";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { getApiErrorMessage } from "@/lib/api/error";
import {
  changeStageFeed,
  choiceOfFeed,
  classifyStageFeed,
  defaultRule,
  sameRule,
  type FeedChoice,
  type FeedRule,
  type StageFeed
} from "@/lib/flow/stageFeed";
import { nodeDraftFormat } from "@/lib/tournament/flow-nodes";
import flowService from "@/services/flow.service";
import type { DraftFormatSettings } from "@/types/draft.types";
import type { Stage, StageType, Tournament } from "@/types/tournament.types";

import { resolveDraftFormat } from "../../../components/draft/setup-model";
import { modesFor } from "./FeedRuleFields";

/** How the formation node feeding the stage forms teams: the two settings of its config this editor owns. */
export interface FormationEdit {
  mode: string;
  draft_format: DraftFormatSettings;
}

export interface StageFeedState {
  /** Null until the flow graph has loaded (or when it failed to). */
  feed: StageFeed | null;
  choice: FeedChoice | null;
  sourceStage: Stage | undefined;
  /** The stages that may feed this one. */
  candidates: Stage[];
  /** The formation's method and draft format, edited here beside the rule; null unless a formation feeds the stage. */
  formation: FormationEdit | null;
  /** Rows of the feed rule and of the formation node are separate drafts of one save. */
  ruleDirty: boolean;
  formationDirty: boolean;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  /** Why the rule cannot be edited, or null when it can. */
  disabledReason: string | null;
  /** Why the formation's method cannot be edited, or null when it can. */
  formationDisabledReason: string | null;
  /** Why the draft format cannot be edited (no grant, or a draft in flight: the server refuses the change too), or null. */
  formatDisabledReason: string | null;
  /** Off the roster shape: one rule per drafted round. */
  draftRounds: number;
  pick: (nodeId: number) => void;
  patch: (patch: Partial<FeedRule>) => void;
  patchFormation: (patch: Partial<FormationEdit>) => void;
  discard: () => void;
  /** Resolves false when the server refused, the reason being in `error`. */
  save: () => Promise<boolean>;
}

/**
 * The «Who advances» draft of one stage: its feed read from the flow graph, the edit in progress and the save that
 * turns the edit into one `flowService.applyChanges`. A stage fed by a formation also edits that formation's method and
 * draft format here: the node upsert rides the same call. A draft of the stage editor's `SaveBar`, like the round times.
 */
export function useStageFeed({
  stage,
  stages,
  stageType,
  tournament,
  canUpdate,
  onChanged
}: {
  stage: Stage;
  stages: Stage[];
  /** The format being edited, saved or not: only a double elimination takes an upper-bracket split. */
  stageType: StageType;
  tournament: Pick<Tournament, "roster_shape" | "roster_locked_by_draft"> | undefined;
  canUpdate: boolean;
  onChanged: () => void;
}): StageFeedState {
  const t = useTranslations("adminBracket.feed");
  const tDraft = useTranslations("draftAdmin");
  const tEditor = useTranslations("adminBracket.editor");
  const flowMessage = useFlowErrorMessage();
  const client = useQueryClient();
  const queryKey = adminQueryKeys.tournamentFlow(stage.tournament_id);
  const flowQuery = useQuery({ queryKey, queryFn: () => flowService.getAdmin(stage.tournament_id) });
  const [draft, setDraft] = useState<FeedChoice | null>(null);
  const [formationDraft, setFormationDraft] = useState<FormationEdit | null>(null);
  const [error, setError] = useState<string | null>(null);

  const feed = flowQuery.data ? classifyStageFeed(flowQuery.data, stage.node_id) : null;
  // Through a formation the rule is the formation's input: it locks with the formation, not with this stage.
  const formation = feed?.kind === "formed" ? feed.formation : null;
  const baseline = feed ? choiceOfFeed(feed, defaultRule(undefined)) : null;
  const choice = draft ?? baseline;
  const sourceStage = stages.find((candidate) => candidate.node_id === choice?.source);
  // A later stage is never offered as a source: the flow would loop. An existing wiring that already does stays listed.
  const candidates = stages.filter(
    (candidate) =>
      candidate.id !== stage.id && (candidate.order < stage.order || candidate.node_id === baseline?.source)
  );

  const ruleDirty =
    draft?.source != null &&
    baseline !== null &&
    (draft.source !== baseline.source || !sameRule(draft.rule, baseline.rule));

  const draftRounds = tournament?.roster_shape?.draft_rounds ?? 0;
  const formationBaseline: FormationEdit | null = formation
    ? {
        mode: String(formation.config.mode ?? "manual"),
        draft_format: resolveDraftFormat(nodeDraftFormat(formation), draftRounds)
      }
    : null;
  const formationEdit = formationDraft ?? formationBaseline;
  // Only the keys that changed are written, so a balancer node never gains a `draft_format` it does not use.
  const formationPatch =
    formationDraft && formationBaseline
      ? Object.fromEntries(
          Object.entries(formationDraft).filter(
            ([key, value]) =>
              JSON.stringify(value) !== JSON.stringify(formationBaseline[key as keyof FormationEdit])
          )
        )
      : {};
  const formationDirty = Object.keys(formationPatch).length > 0;
  const dirty = ruleDirty || formationDirty;

  const edit = (next: FeedChoice) => {
    setError(null);
    setDraft(next);
  };

  const mutation = useMutation({
    mutationFn: (next: { choice: { source: number; rule: FeedRule } | null; formation: Record<string, unknown> }) => {
      const feedChanges = next.choice
        ? changeStageFeed(
            flowQuery.data!,
            stage.node_id,
            {
              ...next.choice,
              rule: {
                ...next.choice.rule,
                upper: stageType === "double_elimination" && !formation ? next.choice.rule.upper : null
              }
            },
            t("filterName")
          )
        : null;
      // The node upsert is a full replace of `config`, so the node's other keys are carried over.
      const formationNode =
        formation && Object.keys(next.formation).length > 0
          ? [{ id: formation.id, kind: formation.kind, name: formation.name, config: { ...formation.config, ...next.formation } }]
          : [];
      const nodes = [...(feedChanges?.nodes ?? []), ...formationNode];
      if (!feedChanges && nodes.length === 0) return Promise.resolve(null);
      return flowService.applyChanges(stage.tournament_id, { ...feedChanges, nodes });
    },
    onSuccess: (read) => {
      if (read) client.setQueryData(queryKey, read);
      setDraft(null);
      setFormationDraft(null);
      onChanged();
    },
    onError: (failure) => setError(flowMessage(failure) ?? getApiErrorMessage(failure, tEditor("saveError")))
  });

  return {
    feed,
    choice,
    sourceStage,
    candidates,
    formation: formationEdit,
    ruleDirty,
    formationDirty,
    dirty,
    saving: mutation.isPending,
    error,
    disabledReason: !canUpdate
      ? t("readOnly")
      : (formation ? formation.status : stage.status) !== "draft"
        ? t(formation ? "formationFrozen" : "frozen")
        : null,
    formationDisabledReason: !canUpdate ? t("readOnly") : formation?.status !== "draft" ? t("formationModeLocked") : null,
    formatDisabledReason: !canUpdate
      ? t("readOnly")
      : tournament?.roster_locked_by_draft === true
        ? tDraft("formatLockedByDraft")
        : null,
    draftRounds,
    pick: (nodeId: number) => {
      const source = stages.find((candidate) => candidate.node_id === nodeId);
      if (!source || !choice) return;
      const keep = modesFor(source).includes(choice.rule.mode) && choice.source != null;
      edit({ source: nodeId, rule: keep ? choice.rule : defaultRule(source) });
    },
    patch: (patch: Partial<FeedRule>) => choice && edit({ ...choice, rule: { ...choice.rule, ...patch } }),
    patchFormation: (patch: Partial<FormationEdit>) => {
      if (!formationEdit) return;
      setError(null);
      setFormationDraft({ ...formationEdit, ...patch });
    },
    discard: () => {
      setError(null);
      setDraft(null);
      setFormationDraft(null);
    },
    save: async () => {
      if (!dirty) return true;
      setError(null);
      const choice = ruleDirty && draft?.source != null ? { source: draft.source, rule: draft.rule } : null;
      return mutation.mutateAsync({ choice, formation: formationPatch }).then(
        () => true,
        () => false
      );
    }
  };
}
