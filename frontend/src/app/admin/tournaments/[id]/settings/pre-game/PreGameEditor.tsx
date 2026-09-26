"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Copy, RotateCcw } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SaveBar } from "@/components/kit/SaveBar";
import {
  isRulesTemplate,
  type PickBanDraft,
  type PickBanScopeEncounter
} from "@/lib/tournament/pick-ban-config";
import type { PickBanConfig, PickBanKind, Stage } from "@/types/tournament.types";

import { type CatalogueItem } from "./CataloguePicker";
import { PoolStep } from "./PoolStep";
import { SequenceStep } from "./SequenceStep";
import { SidesStep } from "./SidesStep";
import { PRE_GAME_STEPS, type PreGameScope, type PreGameStep } from "./pre-game-scope";
import { usePreGameDraft } from "./usePreGameDraft";

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
 *
 * The draft and everything derived from it live in `usePreGameDraft`; each step
 * is its own file. What is left here is the frame: the step strip, the cascade
 * line, the validation summary and the save bar they all share.
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

  const form = usePreGameDraft({ scope, kind, stages, encounters, configs });
  const { draft, inheritedConfig, savedConfig, series } = form;
  const [resetOpen, setResetOpen] = useState(false);

  const catalogueById = useMemo(
    () => new Map(catalogue.map((option) => [option.id, option])),
    [catalogue]
  );

  const scopeLabel = describeScope({ stage_id: scope.stageId, round: scope.round });
  const inheritedLabel =
    inheritedConfig == null
      ? null
      : describeScope({ stage_id: inheritedConfig.stage_id, round: inheritedConfig.round });

  return (
    <div className="flex flex-col gap-4">
      {canManage ? null : <p className="text-sm text-muted-foreground">{t("readOnly")}</p>}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h2 className="font-display text-base font-semibold">{scopeLabel}</h2>
        <span className="text-xs text-muted-foreground">{t(`scopeState.${form.scopeState}`)}</span>
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

      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          {step === "pool" ? (
            <PoolStep
              ids={ids}
              draft={draft}
              kind={kind}
              slotCount={form.slotCount}
              isStageScope={form.isStageScope}
              roundsLoading={form.roundsLoading}
              roundLabelFor={form.roundLabelFor}
              patchRoundSlot={form.patchRoundSlot}
              onModeChange={form.changeMode}
              catalogue={catalogue}
              catalogueById={catalogueById}
              catalogueLoading={catalogueLoading}
              canManage={canManage}
              patch={form.patch}
              patchSlot={form.patchSlot}
              toggleItem={form.toggleItem}
            />
          ) : null}

          {step === "sequence" ? (
            <SequenceStep
              ids={ids}
              draft={draft}
              isHero={isHero}
              series={series}
              sequence={form.sequence}
              canManage={canManage}
              patch={form.patch}
            />
          ) : null}

          {step === "sides" ? (
            <SidesStep
              ids={ids}
              draft={draft}
              isHero={isHero}
              bestOf={series.bestOf}
              inherited={form.inheritedDraft}
              inheritedLabel={inheritedLabel}
              canManage={canManage}
              patch={form.patch}
            />
          ) : null}
        </CardContent>
      </Card>

      {form.issues.length > 0 ? (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden className="size-4" />
          <AlertDescription>
            <p className="font-medium">{t("validationTitle")}</p>
            <ul className="mt-1 list-inside list-disc">
              {form.issues.map((issue) => (
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
          {t("overridesInherited", { scope: inheritedLabel ?? "" })}
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
        dirty={form.dirty && canManage}
        edited={form.edited && canManage}
        saving={saving}
        primaryLabel={t("save")}
        summary={t("editingScope", { scope: scopeLabel })}
        onDiscard={form.discard}
        // Save stays clickable with the reason on screen rather than greying
        // out a viewport away from the alert that explains it.
        onSave={() => {
          if (form.issues.length > 0) return;
          onSave(form.saveJobs());
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
            source: inheritedLabel ?? t("tournamentLevel")
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
