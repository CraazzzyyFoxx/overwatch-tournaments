"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, ArrowDown, ArrowUp, Copy, Plus, RotateCcw, X } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
  FieldTitle
} from "@/components/ui/field";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SaveBar } from "@/components/kit/SaveBar";
import { stageRoundShape } from "@/lib/bracket/view";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { hasUnsavedChanges } from "@/lib/form-change";
import type {
  MapVetoMode,
  PickBanConfig,
  PickBanFirstBanRotation,
  PickBanKind,
  PickBanNoRepeatScope,
  PickBanSequenceToken,
  Stage
} from "@/types/tournament.types";
import {
  PICK_BAN_MODES,
  PICK_BAN_NO_REPEAT_SCOPES,
  PICK_BAN_ROTATIONS,
  PICK_BAN_STEP_ACTIONS,
  PICK_BAN_STEP_SIDES,
  alignSlots,
  buildStepToken,
  effectiveSequence,
  emptyPickBanDraft,
  fanOutRoundDrafts,
  findInheritedConfig,
  isRulesTemplate,
  parseStepToken,
  pickBanDraftFromConfig,
  protectHasNoStep,
  rescopePickBanDraft,
  resolveSeriesLength,
  resolveSlotCount,
  roundSlotsForStage,
  roundsPlayed,
  validatePickBanDraft,
  type PickBanDraft,
  type PickBanDraftSlot,
  type PickBanOrderMode,
  type PickBanScopeEncounter,
  type PickBanStepAction,
  type PickBanStepSide,
  type SeriesLength
} from "@/lib/tournament/pick-ban-config";
import { CatalogueChips, CataloguePicker, type CatalogueItem } from "./CataloguePicker";
import {
  PRE_GAME_STEPS,
  findScopeConfig,
  scopeConfigState,
  type PreGameScope,
  type PreGameStep
} from "./pre-game-scope";
import { useStageRounds } from "./useStageRounds";

export interface PreGameEditorProps {
  scope: PreGameScope;
  kind: PickBanKind;
  step: PreGameStep;
  /**
   * Writes `?step=`. The steps are URL state, but NOT links: they are sections
   * of one form, and `SaveBar`'s unsaved guard intercepts every in-app anchor
   * while the form is dirty — so a link here would demand a discard prompt to
   * look at the sequence you just edited the pool for.
   */
  onStepChange: (step: PreGameStep) => void;
  stages: Stage[];
  encounters?: PickBanScopeEncounter[];
  configs: PickBanConfig[];
  catalogue: CatalogueItem[];
  catalogueLoading: boolean;
  canManage: boolean;
  describeScope: (scope: Pick<PickBanConfig, "stage_id" | "round">) => string;
  saving: boolean;
  resetting: boolean;
  /**
   * One upsert per entry, in order. Slot-mode groups authored on a stage screen
   * are one config per round, so a save is N writes rather than one.
   */
  onSave: (jobs: Array<{ draft: PickBanDraft; seriesLength: number }>) => void;
  /** Drops this scope's own config so it inherits again. */
  onResetToInherited: (configId: number) => void;
}

/**
 * The rules of one scope, as three steps rather than one 700-line form.
 *
 * Pool → Sequence → Sides are sections of the same form addressed by `?step=`,
 * not dialogs and not a wizard: an organizer changing a turn timer must not
 * walk through a pool picker to reach it, and every step saves the same config.
 */
export function PreGameEditor({
  scope,
  kind,
  step,
  onStepChange,
  stages,
  encounters,
  configs,
  catalogue,
  catalogueLoading,
  canManage,
  describeScope,
  saving,
  resetting,
  onSave,
  onResetToInherited
}: Readonly<PreGameEditorProps>) {
  const t = useTranslations("pickBan.admin");
  const ids = useId();
  const isHero = kind === "hero";

  const savedConfig = findScopeConfig(kind, scope, configs);
  const inheritedConfig = findInheritedConfig(kind, scope.stageId, scope.round, configs);

  // What the scope above says today, field by field. A saved override stores a
  // COPY of its parent's rules (`rescopePickBanDraft`) -- usually authored to
  // change the pool, not the rules -- so without this the two diverge silently
  // the moment the tournament level is edited again.
  const inheritedDraft = inheritedConfig == null ? null : pickBanDraftFromConfig(inheritedConfig);
  const inheritedLabel =
    inheritedConfig == null
      ? null
      : describeScope({ stage_id: inheritedConfig.stage_id, round: inheritedConfig.round });

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
  const [resetOpen, setResetOpen] = useState(false);

  const catalogueById = useMemo(
    () => new Map(catalogue.map((option) => [option.id, option])),
    [catalogue]
  );

  const series = resolveSeriesLength(scope.stageId, scope.round, stages, encounters);
  const sequence = effectiveSequence(draft, series.bestOf);
  const issues = validatePickBanDraft(draft, series.bestOf);
  const scopeLabel = describeScope({ stage_id: scope.stageId, round: scope.round });
  const scopeState = scopeConfigState(kind, scope, configs);
  // Two different questions. `edited` is what the organizer has typed here —
  // the only thing leaving this scope can lose, so it is what arms the unsaved
  // guard; clicking through the scope tree used to cost a discard prompt per
  // round because the two were one flag.
  //
  // `dirty` is what the bar has to offer: a scope with no config of its own
  // always has something to save — either the values it was prefilled with
  // from the cascade, or a first rule set for a scope nothing reaches. Only an
  // already-saved config can be clean.
  const edited = hasUnsavedChanges(draft, baseDraft);
  const dirty = savedConfig == null || edited;

  const patch = (values: Partial<PickBanDraft>) =>
    setDraft((current) => ({ ...current, ...values }));

  const toggleItem = (itemId: number) =>
    setDraft((current) => ({
      ...current,
      itemIds: current.itemIds.includes(itemId)
        ? current.itemIds.filter((id) => id !== itemId)
        : [...current.itemIds, itemId]
    }));

  const patchSlot = (index: number, slotPatch: Partial<PickBanDraft["slots"][number]>) =>
    setDraft((current) => ({
      ...current,
      slots: current.slots.map((slot, at) => (at === index ? { ...slot, ...slotPatch } : slot))
    }));

  const patchRoundSlot = (
    roundIndex: number,
    slotIndex: number,
    slotPatch: Partial<PickBanDraft["slots"][number]>
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
    }));

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

  const StepStrip = (
    <nav aria-label={t("stepsLabel")} className="flex flex-wrap gap-1">
      {PRE_GAME_STEPS.map((key, index) => (
        <Button
          key={key}
          type="button"
          size="sm"
          variant={key === step ? "default" : "ghost"}
          aria-current={key === step ? "step" : undefined}
          onClick={() => onStepChange(key)}
        >
          {index + 1} · {t(`step.${key}`)}
        </Button>
      ))}
    </nav>
  );

  return (
    <div className="flex flex-col gap-4">
      {canManage ? null : <p className="text-sm text-muted-foreground">{t("readOnly")}</p>}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h2 className="font-display text-base font-semibold">{scopeLabel}</h2>
        <span className="text-xs text-muted-foreground">{t(`scopeState.${scopeState}`)}</span>
      </div>


      {draft.inheritedFrom != null ? (
        <Alert>
          <Copy aria-hidden className="size-4" />
          <AlertDescription>
            {t("inheritedPrefill", {
              scope: describeScope({
                stage_id: draft.inheritedFrom.stageId,
                round: draft.inheritedFrom.round
              })
            })}
          </AlertDescription>
        </Alert>
      ) : null}

      {StepStrip}

      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          {step === "pool" ? (
            <PoolStep
              ids={ids}
              draft={draft}
              kind={kind}
              slotCount={slotCount}
              isStageScope={isStageScope}
              roundsLoading={roundsLoading}
              roundLabelFor={(round) => roundLabel(round, roundShape)}
              patchRoundSlot={patchRoundSlot}
              onModeChange={changeMode}
              catalogue={catalogue}
              catalogueById={catalogueById}
              catalogueLoading={catalogueLoading}
              canManage={canManage}
              patch={patch}
              patchSlot={patchSlot}
              toggleItem={toggleItem}
            />
          ) : null}

          {step === "sequence" ? (
            <SequenceStep
              ids={ids}
              draft={draft}
              isHero={isHero}
              series={series}
              sequence={sequence}
              canManage={canManage}
              patch={patch}
            />
          ) : null}

          {step === "sides" ? (
            <SidesStep
              ids={ids}
              draft={draft}
              isHero={isHero}
              bestOf={series.bestOf}
              inherited={inheritedDraft}
              inheritedLabel={inheritedLabel}
              canManage={canManage}
              patch={patch}
            />
          ) : null}
        </CardContent>
      </Card>

      {issues.length > 0 ? (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden className="size-4" />
          <AlertDescription>
            <p className="font-medium">{t("validationTitle")}</p>
            <ul className="mt-1 list-inside list-disc">
              {issues.map((issue) => (
                <li key={issue.key}>{t(`validation.${issue.key}`, issue.values)}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* Not a validation error: a pool-less scope saves fine, it just plays
          nothing. Said here rather than in the pool step, because the save that
          stores it can be pressed from any of the three. */}
      {isRulesTemplate(draft) ? (
        <Alert>
          <Copy aria-hidden className="size-4" />
          <AlertDescription>{t("rulesTemplate")}</AlertDescription>
        </Alert>
      ) : null}

      {/* The cascade line: what this scope inherits, and the way back to it.
          Outside the save bar deliberately — dropping an override is the
          common act on a scope with nothing else to save, and a control that
          only appears once the form is dirty could never do it. */}
      {inheritedConfig != null ? (
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {t("overridesInherited", {
            scope: describeScope({
              stage_id: inheritedConfig.stage_id,
              round: inheritedConfig.round
            })
          })}
          {canManage && savedConfig != null ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={resetting}
              onClick={() => setResetOpen(true)}
            >
              <RotateCcw aria-hidden className="me-2 size-3.5" />
              {t("resetToInherited")}
            </Button>
          ) : null}
        </p>
      ) : null}

      <SaveBar
        dirty={dirty && canManage}
        edited={edited && canManage}
        saving={saving}
        primaryLabel={t("save")}
        summary={t("editingScope", { scope: scopeLabel })}
        onDiscard={() => setDraft(baseDraft)}
        // Save stays clickable with the reason on screen rather than greying
        // out a viewport away from the alert that explains it.
        onSave={() => {
          if (issues.length > 0) return;
          onSave(
            fanOutRoundDrafts(draft).map((one) => ({
              draft: one,
              seriesLength:
                one.round == null
                  ? series.bestOf
                  : resolveSeriesLength(scope.stageId, one.round, stages, encounters).bestOf
            }))
          );
        }}
      />

      <ConfirmDialog
        open={resetOpen}
        onOpenChange={setResetOpen}
        pending={resetting}
        intent={{
          title: t("resetConfirmTitle"),
          description: t("resetConfirmDescription", {
            scope: scopeLabel,
            source:
              inheritedConfig == null
                ? t("tournamentLevel")
                : describeScope({
                    stage_id: inheritedConfig.stage_id,
                    round: inheritedConfig.round
                  })
          }),
          confirmLabel: t("resetConfirmAction"),
          tone: "warning"
        }}
        onConfirm={() => {
          if (savedConfig != null) onResetToInherited(savedConfig.id);
          setResetOpen(false);
        }}
      />
    </div>
  );
}

// ── step 1: pool ─────────────────────────────────────────────────────────────

function PoolStep({
  ids,
  draft,
  kind,
  slotCount,
  isStageScope,
  roundsLoading,
  roundLabelFor,
  catalogue,
  catalogueById,
  catalogueLoading,
  canManage,
  patch,
  patchSlot,
  patchRoundSlot,
  onModeChange,
  toggleItem
}: Readonly<{
  ids: string;
  draft: PickBanDraft;
  kind: PickBanKind;
  /** Groups the bracket calls for in a one-round scope; the list is this long. */
  slotCount: number;
  /** A whole stage is on screen, so any groups here cover every round of it. */
  isStageScope: boolean;
  /** The stage's rounds are still being predicted, so they cannot be listed. */
  roundsLoading: boolean;
  /** What the bracket calls a round — "LB Round 1", "Grand Final", not "-1". */
  roundLabelFor: (round: number) => string;
  catalogue: CatalogueItem[];
  catalogueById: Map<number, CatalogueItem>;
  catalogueLoading: boolean;
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
  patchSlot: (index: number, slotPatch: Partial<PickBanDraftSlot>) => void;
  patchRoundSlot: (
    roundIndex: number,
    slotIndex: number,
    slotPatch: Partial<PickBanDraftSlot>
  ) => void;
  /** Owns the round dimension the pool shape decides, so it lives upstairs. */
  onModeChange: (mode: MapVetoMode) => void;
  toggleItem: (itemId: number) => void;
}>) {
  const t = useTranslations("pickBan.admin");
  const isHero = kind === "hero";

  return (
    <>
      <div>
        <FieldTitle className="text-sm">{t("poolSection")}</FieldTitle>
        <FieldDescription>{t("poolSectionHint")}</FieldDescription>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={`${ids}-mode`}>{t("modeLabel")}</FieldLabel>
          <Select
            value={draft.mode}
            disabled={!canManage}
            onValueChange={(value) => onModeChange(value as MapVetoMode)}
          >
            <SelectTrigger id={`${ids}-mode`} aria-describedby={`${ids}-mode-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_MODES.map((mode) => (
                <SelectItem key={mode} value={mode}>
                  {mode === "pool" ? t("modePool") : t("modeSlots")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription id={`${ids}-mode-hint`}>
            {draft.mode === "pool" ? t("modePoolHint") : t("modeSlotsHint")}
          </FieldDescription>
        </Field>
      </div>

      {draft.mode === "pool" ? (
        <Field>
          <FieldTitle className="text-sm">
            {isHero ? t("poolHeroLabel") : t("poolMapLabel")}
            <Badge variant="secondary">{t("poolCount", { count: draft.itemIds.length })}</Badge>
          </FieldTitle>
          <FieldDescription>{t("poolHint")}</FieldDescription>
          <CatalogueChips
            itemIds={draft.itemIds}
            catalogue={catalogueById}
            disabled={!canManage}
            onRemove={toggleItem}
            leading={
              <CataloguePicker
                mode="multi"
                kind={kind}
                options={catalogue}
                selectedIds={draft.itemIds}
                disabled={catalogueLoading || !canManage}
                onToggle={toggleItem}
                onSelectVisible={(itemIds) =>
                  patch({
                    itemIds: [
                      ...draft.itemIds,
                      ...itemIds.filter((id) => !draft.itemIds.includes(id))
                    ]
                  })
                }
                onClearVisible={(itemIds) =>
                  patch({ itemIds: draft.itemIds.filter((id) => !itemIds.includes(id)) })
                }
              />
            }
          />
        </Field>
      ) : draft.roundSlots.length > 0 ? (
        <div className="flex flex-col gap-4">
          <FieldDescription>{t("roundGroupsHint")}</FieldDescription>

          {draft.roundSlots.map((section, roundIndex) => (
            <div
              key={section.round}
              className="flex flex-col gap-2 rounded-xl border border-border bg-muted/20 p-3"
            >
              <FieldTitle className="text-sm">
                {roundLabelFor(section.round)}
                <Badge variant="outline">
                  {t("roundGroupCount", { count: section.slots.length })}
                </Badge>
              </FieldTitle>

              {section.slots.map((slot, index) => (
                <SlotCard
                  key={index}
                  label={t("slotTitle", { n: index + 1 })}
                  reserveLabel={t("slotReserveAria", { n: index + 1 })}
                  slot={slot}
                  kind={kind}
                  catalogue={catalogue}
                  catalogueById={catalogueById}
                  catalogueLoading={catalogueLoading}
                  canManage={canManage}
                  onPatch={(slotPatch) => patchRoundSlot(roundIndex, index, slotPatch)}
                />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <FieldDescription>
            {roundsLoading
              ? t("roundHintLoading")
              : isStageScope
                ? t("roundsUnknownStageWide")
                : t("slotCountFromBracket", { maps: slotCount })}
          </FieldDescription>

          {draft.slots.map((slot, index) => (
            <SlotCard
              key={index}
              label={t("slotTitle", { n: index + 1 })}
              reserveLabel={t("slotReserveAria", { n: index + 1 })}
              slot={slot}
              kind={kind}
              catalogue={catalogue}
              catalogueById={catalogueById}
              catalogueLoading={catalogueLoading}
              canManage={canManage}
              onPatch={(slotPatch) => patchSlot(index, slotPatch)}
            />
          ))}
        </div>
      )}
    </>
  );
}

/**
 * One group: its candidates in play order, its reserve, and the pickers for
 * both. The same card whether it belongs to a single round's scope or to one
 * round of a stage screen — only where the patch lands differs.
 */
function SlotCard({
  label,
  reserveLabel,
  slot,
  kind,
  catalogue,
  catalogueById,
  catalogueLoading,
  canManage,
  onPatch
}: Readonly<{
  label: string;
  reserveLabel: string;
  slot: PickBanDraftSlot;
  kind: PickBanKind;
  catalogue: CatalogueItem[];
  catalogueById: Map<number, CatalogueItem>;
  catalogueLoading: boolean;
  canManage: boolean;
  onPatch: (slotPatch: Partial<PickBanDraftSlot>) => void;
}>) {
  const t = useTranslations("pickBan.admin");

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FieldTitle className="text-sm">
          {label}
          <Badge variant="secondary">
            {t("slotCandidates", { count: slot.candidates.length })}
          </Badge>
        </FieldTitle>
        <CataloguePicker
          mode="single"
          kind={kind}
          triggerLabel={reserveLabel}
          triggerPrefix={t("slotReserve")}
          value={slot.reserveItemId}
          // The server rejects a reserve that is also a candidate, so it is
          // never offered here.
          options={catalogue.filter((option) => !slot.candidates.includes(option.id))}
          disabled={catalogueLoading || !canManage}
          onChange={(itemId) => onPatch({ reserveItemId: itemId })}
        />
      </div>

      <CatalogueChips
        itemIds={slot.candidates}
        catalogue={catalogueById}
        disabled={!canManage}
        onRemove={(itemId) =>
          onPatch({ candidates: slot.candidates.filter((id) => id !== itemId) })
        }
        leading={
          <CataloguePicker
            mode="multi"
            kind={kind}
            options={catalogue}
            selectedIds={slot.candidates}
            disabled={catalogueLoading || !canManage}
            onToggle={(itemId) =>
              onPatch({
                candidates: slot.candidates.includes(itemId)
                  ? slot.candidates.filter((id) => id !== itemId)
                  : [...slot.candidates, itemId],
                // A candidate can no longer be this group's reserve.
                reserveItemId: slot.reserveItemId === itemId ? null : slot.reserveItemId
              })
            }
            onSelectVisible={(itemIds) =>
              onPatch({
                candidates: [
                  ...slot.candidates,
                  ...itemIds.filter((id) => !slot.candidates.includes(id))
                ],
                // The catalogue offered here isn't narrowed like the reserve
                // picker's is, so a bulk add can catch the current reserve;
                // drop it rather than leave a candidate double-booked as its
                // own group's reserve.
                reserveItemId:
                  slot.reserveItemId != null && itemIds.includes(slot.reserveItemId)
                    ? null
                    : slot.reserveItemId
              })
            }
            onClearVisible={(itemIds) =>
              onPatch({ candidates: slot.candidates.filter((id) => !itemIds.includes(id)) })
            }
          />
        }
      />
      <FieldDescription>{t("slotReserveHint")}</FieldDescription>
    </div>
  );
}

// ── step 2: sequence ─────────────────────────────────────────────────────────

function SequenceStep({
  ids,
  draft,
  isHero,
  series,
  sequence,
  canManage,
  patch
}: Readonly<{
  ids: string;
  draft: PickBanDraft;
  isHero: boolean;
  series: SeriesLength;
  sequence: PickBanSequenceToken[];
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
}>) {
  const t = useTranslations("pickBan.admin");

  return (
    <>
      <div>
        <FieldTitle className="text-sm">{t("orderSection")}</FieldTitle>
        <FieldDescription>
          {isHero ? t("orderHeroHint") : t("orderSectionHint")}
        </FieldDescription>
      </div>

      {/* Slot mode resolves each round on its own; there is no series-wide
          order to author, and the custom preset is unstorable. */}
      {draft.mode === "slots" ? (
        <FieldDescription>{t("orderSlotsMode")}</FieldDescription>
      ) : (
        <>
          {/* A hero config has no bracket-generated option: its sequence is ONE
              round's steps, replayed per map of the series, while the generator
              answers the map question and emits picks and a decider a hero
              round cannot resolve. */}
          {isHero ? null : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor={`${ids}-order`}>{t("orderLabel")}</FieldLabel>
                <Select
                  value={draft.orderMode}
                  disabled={!canManage}
                  onValueChange={(value) =>
                    patch({
                      orderMode: value as PickBanOrderMode,
                      // Authoring starts from the generated order rather than
                      // an empty list, so "custom" is an edit, not a blank page.
                      sequence:
                        value === "custom" && draft.sequence.length === 0
                          ? sequence
                          : draft.sequence
                    })
                  }
                >
                  <SelectTrigger id={`${ids}-order`} aria-describedby={`${ids}-order-hint`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bracket">{t("orderBracket")}</SelectItem>
                    <SelectItem value="custom">{t("orderCustom")}</SelectItem>
                  </SelectContent>
                </Select>
                <FieldDescription id={`${ids}-order-hint`}>
                  {draft.orderMode === "bracket" ? t("orderBracketHint") : t("orderCustomHint")}
                </FieldDescription>
              </Field>
            </div>
          )}

          {/* The generated order is a function of the pool, so it says nothing
              until there is one — "0 rounds played" would read as a setting
              rather than a missing prerequisite. */}
          {draft.itemIds.length === 0 ? (
            <FieldDescription>{t("orderNeedsPool")}</FieldDescription>
          ) : (
            <div className="flex flex-col gap-2">
              <FieldTitle className="text-sm">
                {draft.orderMode === "bracket" ? t("orderPreview") : t("orderSteps")}
                {/* "Rounds played" counts picks and deciders — the maps a map
                    sequence settles. A hero round plays no map of its own. */}
                {isHero ? null : (
                  <Badge variant="secondary">
                    {t("orderRoundsPlayed", { count: roundsPlayed(sequence) })}
                  </Badge>
                )}
              </FieldTitle>

              {draft.orderMode === "bracket" ? (
                <>
                  <FieldDescription>
                    {t(`seriesSource.${series.source}`, { bestOf: series.bestOf })}
                  </FieldDescription>
                  <SequencePreview sequence={sequence} />
                </>
              ) : (
                <>
                  {/* A custom order runs as written, so the scope's series
                      length is only worth raising when the two disagree — and
                      only where the length is exact rather than a preview. */}
                  {!isHero &&
                  series.source === "round" &&
                  roundsPlayed(sequence) !== series.bestOf ? (
                    <Alert>
                      <AlertTriangle aria-hidden className="size-4" />
                      <AlertDescription>
                        {t("orderCustomMismatch", {
                          played: roundsPlayed(sequence),
                          expected: series.bestOf
                        })}
                      </AlertDescription>
                    </Alert>
                  ) : null}
                  <StepList
                    sequence={draft.sequence}
                    allowProtect={draft.allowProtect}
                    allowDecider={!isHero}
                    disabled={!canManage}
                    onChange={(next) => patch({ sequence: next })}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}

/** Read-only step chips: the generated order, or a preview of a custom one. */
function SequencePreview({ sequence }: Readonly<{ sequence: PickBanSequenceToken[] }>) {
  const t = useTranslations("pickBan.admin");
  if (sequence.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("sequenceEmpty")}</p>;
  }
  return (
    <ol className="flex flex-wrap gap-1.5">
      {sequence.map((token, index) => {
        const step = parseStepToken(token);
        return (
          <li
            key={`${token}-${index}`}
            className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs"
          >
            <span className="text-muted-foreground tabular-nums">{index + 1}</span>
            <span className="font-medium">
              {step.side == null
                ? t("action.decider")
                : `${t(`action.${step.action}`)} · ${t(`side.${step.side}`)}`}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The hand-authored step list. Reachable in pool mode with custom order only. */
function StepList({
  sequence,
  allowProtect,
  allowDecider,
  disabled,
  onChange
}: Readonly<{
  sequence: PickBanSequenceToken[];
  /** Gates the protect action: the engine ignores it without the toggle. */
  allowProtect: boolean;
  /** False for a hero sequence, whose pool has no survivor to decide on. */
  allowDecider: boolean;
  disabled: boolean;
  onChange: (next: PickBanSequenceToken[]) => void;
}>) {
  const t = useTranslations("pickBan.admin");

  const replace = (index: number, token: PickBanSequenceToken) => {
    const next = [...sequence];
    next[index] = token;
    onChange(next);
  };

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= sequence.length) return;
    const next = [...sequence];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const actions: (PickBanStepAction | "decider")[] = [
    ...PICK_BAN_STEP_ACTIONS.filter((action) => action !== "protect" || allowProtect),
    ...(allowDecider ? (["decider"] as const) : [])
  ];

  return (
    <div className="flex flex-col gap-2">
      {sequence.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("sequenceEmpty")}</p>
      ) : null}

      <ol className="flex flex-col gap-2">
        {sequence.map((token, index) => {
          const step = parseStepToken(token);
          const position = index + 1;
          return (
            <li key={index} className="flex flex-wrap items-center gap-2">
              <span className="w-14 shrink-0 text-xs text-muted-foreground tabular-nums">
                {t("stepNumber", { n: position })}
              </span>

              <Select
                value={step.action}
                disabled={disabled}
                onValueChange={(value) =>
                  replace(
                    index,
                    buildStepToken(value as PickBanStepAction | "decider", step.side ?? "first")
                  )
                }
              >
                <SelectTrigger className="w-36" aria-label={t("stepActionLabel", { n: position })}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {actions.map((action) => (
                    <SelectItem key={action} value={action}>
                      {t(`action.${action}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {step.side == null ? (
                <span className="text-xs text-muted-foreground">{t("deciderAuto")}</span>
              ) : (
                <Select
                  value={step.side}
                  disabled={disabled}
                  onValueChange={(value) =>
                    replace(index, buildStepToken(step.action, value as PickBanStepSide))
                  }
                >
                  <SelectTrigger className="w-36" aria-label={t("stepSideLabel", { n: position })}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PICK_BAN_STEP_SIDES.map((side) => (
                      <SelectItem key={side} value={side}>
                        {t(`side.${side}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}

              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={disabled || index === 0}
                  aria-label={t("stepMoveUp", { n: position })}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp aria-hidden className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={disabled || index === sequence.length - 1}
                  aria-label={t("stepMoveDown", { n: position })}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown aria-hidden className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={disabled}
                  aria-label={t("stepRemove", { n: position })}
                  onClick={() => onChange(sequence.filter((_, at) => at !== index))}
                >
                  <X aria-hidden className="size-4" />
                </Button>
              </div>
            </li>
          );
        })}
      </ol>

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        disabled={disabled}
        onClick={() => onChange([...sequence, "ban_first"])}
      >
        <Plus aria-hidden className="me-2 size-4" />
        {t("addStep")}
      </Button>
    </div>
  );
}

// ── step 3: sides ────────────────────────────────────────────────────────────

/**
 * One rule field's provenance: what the scope above sets it to, and one click
 * back to that value.
 *
 * Inheritance is per CONFIG, not per field -- a scope either has its own rule
 * set or plays by an ancestor's. This is what makes that legible on a scope
 * that DOES have its own: which of its values still agree with the level above,
 * and which one it is actually overriding.
 */
function InheritedNote({
  scope,
  same,
  value,
  canManage,
  onReset
}: Readonly<{
  scope: string;
  same: boolean;
  value: string;
  canManage: boolean;
  onReset: () => void;
}>) {
  const t = useTranslations("pickBan.admin");

  if (same) return <FieldDescription>{t("sameAsScope", { scope })}</FieldDescription>;

  return (
    <FieldDescription className="flex flex-wrap items-center gap-1">
      <span>{t("inheritedValue", { scope, value })}</span>
      {canManage ? (
        <Button type="button" variant="ghost" size="sm" className="h-6 px-2" onClick={onReset}>
          <RotateCcw aria-hidden className="me-1 size-3" />
          {t("useInheritedValue")}
        </Button>
      ) : null}
    </FieldDescription>
  );
}

function SidesStep({
  ids,
  draft,
  isHero,
  bestOf,
  inherited,
  inheritedLabel,
  canManage,
  patch
}: Readonly<{
  ids: string;
  draft: PickBanDraft;
  isHero: boolean;
  bestOf: number;
  /** Rules of the scope above, or null at the tournament level. */
  inherited: PickBanDraft | null;
  inheritedLabel: string | null;
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
}>) {
  const t = useTranslations("pickBan.admin");
  const protectUnused = protectHasNoStep(draft, bestOf);

  return (
    <>
      <div>
        <FieldTitle className="text-sm">{t("rulesSection")}</FieldTitle>
        <FieldDescription>{t("rulesSectionHint")}</FieldDescription>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={`${ids}-rotation`}>{t("firstBanRotation")}</FieldLabel>
          <Select
            value={draft.firstBanRotation}
            disabled={!canManage}
            onValueChange={(value) =>
              patch({ firstBanRotation: value as PickBanFirstBanRotation })
            }
          >
            <SelectTrigger id={`${ids}-rotation`} aria-describedby={`${ids}-rotation-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_ROTATIONS.map((rotation) => (
                <SelectItem key={rotation} value={rotation}>
                  {t(`firstBanRotationValue.${rotation}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription id={`${ids}-rotation-hint`}>
            {t(`firstBanRotationHint.${draft.firstBanRotation}`)}
          </FieldDescription>
          {inherited != null && inheritedLabel != null ? (
            <InheritedNote
              scope={inheritedLabel}
              same={draft.firstBanRotation === inherited.firstBanRotation}
              value={t(`firstBanRotationValue.${inherited.firstBanRotation}`)}
              canManage={canManage}
              onReset={() => patch({ firstBanRotation: inherited.firstBanRotation })}
            />
          ) : null}
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-norepeat`}>{t("noRepeatScope")}</FieldLabel>
          <Select
            value={draft.noRepeatScope}
            disabled={!canManage}
            onValueChange={(value) => patch({ noRepeatScope: value as PickBanNoRepeatScope })}
          >
            <SelectTrigger id={`${ids}-norepeat`} aria-describedby={`${ids}-norepeat-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_NO_REPEAT_SCOPES.map((scope) => (
                <SelectItem key={scope} value={scope}>
                  {t(`noRepeatScopeValue.${scope}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription id={`${ids}-norepeat-hint`}>
            {t(`noRepeatScopeHint.${draft.noRepeatScope}`)}
          </FieldDescription>
          {inherited != null && inheritedLabel != null ? (
            <InheritedNote
              scope={inheritedLabel}
              same={draft.noRepeatScope === inherited.noRepeatScope}
              value={t(`noRepeatScopeValue.${inherited.noRepeatScope}`)}
              canManage={canManage}
              onReset={() => patch({ noRepeatScope: inherited.noRepeatScope })}
            />
          ) : null}
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-timer`}>{t("turnTimer")}</FieldLabel>
          <div className="flex items-center gap-2">
            <NumberInput
              id={`${ids}-timer`}
              aria-describedby={`${ids}-timer-hint`}
              min={1}
              integer
              disabled={!canManage}
              placeholder={t("turnTimerPlaceholder")}
              className="w-28"
              value={draft.turnTimerSeconds}
              onValueChange={(value) => patch({ turnTimerSeconds: value })}
            />
            <span className="text-sm text-muted-foreground">{t("turnTimerUnit")}</span>
            {draft.turnTimerSeconds != null ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={!canManage}
                onClick={() => patch({ turnTimerSeconds: null })}
              >
                <RotateCcw aria-hidden className="me-2 size-3.5" />
                {t("turnTimerClear")}
              </Button>
            ) : null}
          </div>
          <FieldDescription id={`${ids}-timer-hint`}>{t("turnTimerHint")}</FieldDescription>
          {inherited != null && inheritedLabel != null ? (
            <InheritedNote
              scope={inheritedLabel}
              same={draft.turnTimerSeconds === inherited.turnTimerSeconds}
              value={
                inherited.turnTimerSeconds == null
                  ? t("turnTimerPlaceholder")
                  : `${inherited.turnTimerSeconds} ${t("turnTimerUnit")}`
              }
              canManage={canManage}
              onReset={() => patch({ turnTimerSeconds: inherited.turnTimerSeconds })}
            />
          ) : null}
        </Field>

        <Field>
          <FieldTitle className="text-sm">{t("firstPickRule")}</FieldTitle>
          {/* One enum member exists server-side, so a control here would be a
              choice with nothing to choose. Stated instead of offered. */}
          <p className="text-sm font-medium">{t("firstPickRuleValue.higher_seed")}</p>
          <FieldDescription>{t("firstPickRuleHint")}</FieldDescription>
        </Field>
      </div>

      <Field orientation="horizontal">
        <Switch
          id={`${ids}-protect`}
          aria-describedby={`${ids}-protect-hint`}
          checked={draft.allowProtect}
          disabled={!canManage}
          onCheckedChange={(checked) => patch({ allowProtect: checked })}
        />
        <FieldContent>
          <FieldLabel htmlFor={`${ids}-protect`}>{t("allowProtect")}</FieldLabel>
          <FieldDescription id={`${ids}-protect-hint`}>{t("allowProtectHint")}</FieldDescription>
          {inherited != null && inheritedLabel != null ? (
            <InheritedNote
              scope={inheritedLabel}
              same={draft.allowProtect === inherited.allowProtect}
              value={t(inherited.allowProtect ? "valueOn" : "valueOff")}
              canManage={canManage}
              onReset={() => patch({ allowProtect: inherited.allowProtect })}
            />
          ) : null}
        </FieldContent>
      </Field>

      {protectUnused ? (
        <Alert>
          <AlertTriangle aria-hidden className="size-4" />
          <AlertDescription>{t("protectWithoutStep")}</AlertDescription>
        </Alert>
      ) : null}

      {isHero ? (
        <Field orientation="horizontal">
          <Switch
            id={`${ids}-role`}
            aria-describedby={`${ids}-role-hint`}
            checked={draft.uniqueRolePerRound}
            disabled={!canManage}
            onCheckedChange={(checked) => patch({ uniqueRolePerRound: checked })}
          />
          <FieldContent>
            <FieldLabel htmlFor={`${ids}-role`}>{t("uniqueRole")}</FieldLabel>
            <FieldDescription id={`${ids}-role-hint`}>{t("uniqueRoleHint")}</FieldDescription>
            {inherited != null && inheritedLabel != null ? (
              <InheritedNote
                scope={inheritedLabel}
                same={draft.uniqueRolePerRound === inherited.uniqueRolePerRound}
                value={t(inherited.uniqueRolePerRound ? "valueOn" : "valueOff")}
                canManage={canManage}
                onReset={() => patch({ uniqueRolePerRound: inherited.uniqueRolePerRound })}
              />
            ) : null}
          </FieldContent>
        </Field>
      ) : null}
    </>
  );
}
