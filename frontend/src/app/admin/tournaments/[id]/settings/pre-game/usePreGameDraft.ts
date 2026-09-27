"use client";

import { useMemo, useState } from "react";

import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { stageRoundShape } from "@/lib/bracket/view";
import { hasUnsavedChanges } from "@/lib/form-change";
import {
  alignSlots,
  effectiveSequence,
  emptyPickBanDraft,
  fanOutRoundDrafts,
  findInheritedConfig,
  pickBanDraftFromConfig,
  rescopePickBanDraft,
  resolveSeriesLength,
  resolveSlotCount,
  roundSlotsForStage,
  validatePickBanDraft,
  type PickBanDraft,
  type PickBanDraftSlot,
  type PickBanScopeEncounter
} from "@/lib/tournament/pick-ban-config";
import type {
  MapVetoMode,
  PickBanConfig,
  PickBanKind,
  Stage
} from "@/types/tournament.types";

import { findScopeConfig, scopeConfigState, type PreGameScope } from "./pre-game-scope";
import { useStageRounds } from "./useStageRounds";

/**
 * One scope's rules as an editable draft: what it says today, what the
 * organizer has typed over it, and everything derived from the two.
 *
 * Its own hook because the editor's three steps all read the same draft and
 * none of them owns it — and because the re-baselining below is the subtle part
 * of this screen: a scope switch must not look like an unsaved edit.
 */
export function usePreGameDraft({
  scope,
  kind,
  stages,
  encounters,
  configs
}: Readonly<{
  scope: PreGameScope;
  kind: PickBanKind;
  stages: Stage[];
  encounters?: PickBanScopeEncounter[];
  configs: PickBanConfig[];
}>) {
  const savedConfig = findScopeConfig(kind, scope, configs);
  const inheritedConfig = findInheritedConfig(kind, scope.stageId, scope.round, configs);

  // What the scope above says today, field by field. A saved override stores a
  // COPY of its parent's rules (`rescopePickBanDraft`) -- usually authored to
  // change the pool, not the rules -- so without this the two diverge silently
  // the moment the tournament level is edited again.
  const inheritedDraft = inheritedConfig == null ? null : pickBanDraftFromConfig(inheritedConfig);

  const slotCount = resolveSlotCount(scope.stageId, scope.round, stages, encounters);

  // A stage covers several rounds of the bracket, and a regulation routinely
  // plays different maps in each. A config's scope key is `(stage, round)`, so
  // that is N configs: the stage screen authors all of them at once and fans
  // them out on save (`fanOutRoundDrafts`), which is the only way an organizer
  // sees Round 1's maps next to Round 2's.
  const isStageScope = scope.stageId != null && scope.round == null;
  const stage = stages.find((candidate) => candidate.id === scope.stageId);
  const { rounds, loading: roundsLoading } = useStageRounds(
    isStageScope ? stage : null,
    encounters
  );
  const roundShape = stageRoundShape(scope.stageId, stage?.stage_type, rounds, encounters);
  const roundLabel = useBracketRoundLabel();

  // A stage screen that saved per-round groups leaves nothing at the stage
  // level, so it has to reopen on what its rounds store — otherwise the groups
  // an organizer just authored come back as "one shared pool".
  // Earliest round first, so two rounds with different timers cannot make the
  // screen open on whichever config the list happened to return first.
  const roundSlotSource = isStageScope
    ? rounds
        .map((round) =>
          configs.find(
            (config) =>
              config.kind === kind &&
              config.stage_id === scope.stageId &&
              config.round === round &&
              config.mode === "slots"
          )
        )
        .find((config) => config != null)
    : undefined;

  // What this scope says today: its own saved config, the rules its rounds
  // play by, or a copy of whatever it inherits — retyping the tournament's
  // timer, rotation and pool onto every round is the work organizers skipped,
  // leaving rounds on rules nobody chose.
  //
  // Slot-mode groups are resized to the bracket on the way in: a stored count
  // the bracket has since outgrown would keep the room shut, and the extra
  // groups of a shrunk one are unplayable groups whose emptiness blocked the
  // save of every other change on the form.
  const baseDraft = useMemo(() => {
    const source = savedConfig ?? roundSlotSource;
    const stored =
      source != null
        ? {
            ...pickBanDraftFromConfig(source),
            configId: savedConfig?.id ?? null,
            stageId: scope.stageId,
            round: scope.round
          }
        : rescopePickBanDraft(emptyPickBanDraft(kind), scope.stageId, scope.round, configs);
    if (stored.mode !== "slots") return stored;
    if (isStageScope && rounds.length > 0) {
      return {
        ...stored,
        slots: [],
        roundSlots: roundSlotsForStage({
          kind,
          stageId: scope.stageId as number,
          rounds,
          configs,
          fallback: stored.slots,
          slotCountFor: (round) => resolveSlotCount(scope.stageId, round, stages, encounters)
        })
      };
    }
    return { ...stored, slots: alignSlots(stored.slots, slotCount) };
  }, [
    savedConfig,
    roundSlotSource,
    kind,
    scope.stageId,
    scope.round,
    configs,
    slotCount,
    isStageScope,
    rounds,
    stages,
    encounters
  ]);

  const [draft, setDraft] = useState<PickBanDraft>(baseDraft);
  // Re-baseline on a scope or kind switch, and when another admin's write
  // arrives through the configs query. Done during render, not in an effect:
  // `edited`/`dirty` below compare `draft` against `baseDraft`, so an effect
  // would commit one render where the two belong to different scopes and the
  // unsaved-changes guard fires on a switch the organizer did not make.
  const [baseline, setBaseline] = useState(baseDraft);
  if (baseline !== baseDraft) {
    setBaseline(baseDraft);
    setDraft(baseDraft);
  }

  const series = resolveSeriesLength(scope.stageId, scope.round, stages, encounters);
  const sequence = effectiveSequence(draft, series.bestOf);
  const issues = validatePickBanDraft(draft, series.bestOf);

  const patch = (values: Partial<PickBanDraft>) =>
    setDraft((current) => ({ ...current, ...values }));

  /**
   * Switching into per-group mode used to land on an empty list and a
   * validation error. The bracket already says how many groups there are —
   * and, on a stage, which rounds they belong to — so they are there to fill.
   */
  const changeMode = (mode: MapVetoMode) => {
    if (mode !== "slots") return patch({ mode });
    if (isStageScope && rounds.length > 0) {
      return patch({
        mode,
        slots: [],
        roundSlots: roundSlotsForStage({
          kind,
          stageId: scope.stageId as number,
          rounds,
          configs,
          fallback: draft.slots,
          slotCountFor: (round) => resolveSlotCount(scope.stageId, round, stages, encounters)
        })
      });
    }
    patch({ mode, slots: alignSlots(draft.slots, slotCount) });
  };

  const edited = hasUnsavedChanges(draft, baseDraft);

  return {
    draft,
    baseDraft,
    savedConfig,
    inheritedConfig,
    inheritedDraft,
    slotCount,
    isStageScope,
    rounds,
    roundsLoading,
    series,
    sequence,
    issues,
    scopeState: scopeConfigState(kind, scope, configs),
    // Two different questions. `edited` is what the organizer has typed here —
    // the only thing leaving this scope can lose, so it is what arms the
    // unsaved guard; clicking through the scope tree used to cost a discard
    // prompt per round because the two were one flag.
    //
    // `dirty` is what the bar has to offer: a scope with no config of its own
    // always has something to save — either the values it was prefilled with
    // from the cascade, or a first rule set for a scope nothing reaches. Only
    // an already-saved config can be clean.
    edited,
    dirty: savedConfig == null || edited,
    /** What the bracket calls a round — "LB Round 1", "Grand Final", not "-1". */
    roundLabelFor: (round: number) => roundLabel(round, roundShape),
    discard: () => setDraft(baseDraft),
    patch,
    changeMode,
    toggleItem: (itemId: number) =>
      setDraft((current) => ({
        ...current,
        itemIds: current.itemIds.includes(itemId)
          ? current.itemIds.filter((id) => id !== itemId)
          : [...current.itemIds, itemId]
      })),
    patchSlot: (index: number, slotPatch: Partial<PickBanDraftSlot>) =>
      setDraft((current) => ({
        ...current,
        slots: current.slots.map((slot, at) => (at === index ? { ...slot, ...slotPatch } : slot))
      })),
    patchRoundSlot: (
      roundIndex: number,
      slotIndex: number,
      slotPatch: Partial<PickBanDraftSlot>
    ) =>
      setDraft((current) => ({
        ...current,
        roundSlots: current.roundSlots.map((section, at) =>
          at === roundIndex
            ? {
                ...section,
                slots: section.slots.map((slot, index) =>
                  index === slotIndex ? { ...slot, ...slotPatch } : slot
                )
              }
            : section
        )
      })),
    /**
     * One upsert per entry, in order. Slot-mode groups authored on a stage
     * screen are one config per round, so a save is N writes rather than one —
     * each against the series length of the round it lands on.
     */
    saveJobs: () =>
      fanOutRoundDrafts(draft).map((one) => ({
        draft: one,
        seriesLength:
          one.round == null
            ? series.bestOf
            : resolveSeriesLength(scope.stageId, one.round, stages, encounters).bestOf
      }))
  };
}
