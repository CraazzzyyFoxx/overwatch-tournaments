"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Download, RotateCcw, Upload } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { notify } from "@/lib/notify";
import {
  PICK_BAN_TIMEOUTS,
  parseRulesetJson,
  type PickBanDraft,
  type SeriesLength,
} from "@/lib/tournament/pick-ban-config";
import type {
  PickBanKind,
  PickBanRuleset,
  PickBanRulesIssue,
  PickBanTimeoutPolicy,
} from "@/types/tournament.types";

import type { CatalogueItem } from "./CataloguePicker";
import { IssueList } from "./rules/IssueList";
import { PhaseBoard } from "./rules/PhaseBoard";
import { SeriesPreview } from "./rules/SeriesPreview";
import { StepInspector } from "./rules/StepInspector";
import { useRulesCatalog } from "./rules/useRulesCatalog";

/**
 * Step 2: the rules constructor.
 *
 * The ruleset is one document (phases → steps → conditions), so this screen is
 * one board rather than a wizard: presets seed it, the phase board is the map
 * of it, the inspector edits whichever step is selected, and the preview says
 * what the whole thing does to a Bo1/2/3/5.
 */
export function RulesStep({
  tournamentId,
  draft,
  kind,
  series,
  issues,
  validating,
  inherited,
  inheritedLabel,
  catalogue,
  canManage,
  patch,
}: Readonly<{
  tournamentId: number;
  draft: PickBanDraft;
  kind: PickBanKind;
  series: SeriesLength;
  /** The engine's verdict on this ruleset; errors block the save. */
  issues: PickBanRulesIssue[];
  validating: boolean;
  /** Rules of the scope above, or null at the tournament level. */
  inherited: PickBanDraft | null;
  inheritedLabel: string | null;
  catalogue: CatalogueItem[];
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const ids = useId();
  const catalogQuery = useRulesCatalog();
  const [selected, setSelected] = useState<{ phaseId: string; stepId: string } | null>(null);

  const ruleset = draft.ruleset;
  const setRuleset = (next: PickBanRuleset) => patch({ ruleset: next });

  const presets = (catalogQuery.data?.presets ?? []).filter(
    (preset) => preset.kind === kind && preset.modes.includes(draft.mode)
  );

  const selectedPhase = ruleset.phases.find((phase) => phase.id === selected?.phaseId);
  const selectedStep = selectedPhase?.steps.find((step) => step.id === selected?.stepId);

  return (
    <>
      <div>
        <FieldTitle className="text-sm">{t("title")}</FieldTitle>
        <FieldDescription>{t("hint")}</FieldDescription>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          value=""
          disabled={!canManage || presets.length === 0}
          onValueChange={(id) => {
            const preset = presets.find((candidate) => candidate.id === id);
            if (preset == null) return;
            setSelected(null);
            setRuleset(preset.ruleset);
          }}
        >
          <SelectTrigger className="w-64" aria-label={t("presets")}>
            <SelectValue placeholder={t("presets")} />
          </SelectTrigger>
          <SelectContent>
            {presets.map((preset) => {
              const key = `preset.${preset.id}` as "preset.hero_anti_one_trick";
              return (
                <SelectItem key={preset.id} value={preset.id}>
                  {t.has(key) ? t(key) : preset.id}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>

        <JsonTransfer ruleset={ruleset} canManage={canManage} onImport={setRuleset} />

        <div className="flex-1" />

        {inherited != null && inheritedLabel != null ? (
          <InheritedRuleset
            scope={inheritedLabel}
            same={JSON.stringify(inherited.ruleset) === JSON.stringify(ruleset)}
            canManage={canManage}
            onReset={() => {
              setSelected(null);
              setRuleset(inherited.ruleset);
            }}
          />
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={`${ids}-timer`}>{t("timer")}</FieldLabel>
          <NumberInput
            id={`${ids}-timer`}
            className="w-28"
            integer
            min={5}
            disabled={!canManage}
            placeholder={t("timerOff")}
            value={ruleset.timer_seconds}
            onValueChange={(value) => setRuleset({ ...ruleset, timer_seconds: value })}
          />
          <FieldDescription>{t("timerHint")}</FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-timeout`}>{t("onTimeoutLabel")}</FieldLabel>
          <Select
            value={ruleset.on_timeout}
            disabled={!canManage}
            onValueChange={(value) =>
              setRuleset({ ...ruleset, on_timeout: value as PickBanTimeoutPolicy })
            }
          >
            <SelectTrigger id={`${ids}-timeout`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_TIMEOUTS.map((policy) => (
                <SelectItem key={policy} value={policy}>
                  {t(`onTimeout.${policy}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription>{t(`onTimeoutHint.${ruleset.on_timeout}`)}</FieldDescription>
        </Field>
      </div>

      <PhaseBoard
        ruleset={ruleset}
        kind={kind}
        catalog={catalogQuery.data}
        catalogue={catalogue}
        issues={issues}
        selected={selected}
        canManage={canManage}
        onChange={setRuleset}
        onSelect={setSelected}
      />

      {/* Issues the validator files against the ruleset itself rather than a
          phase — a timer below the floor, a missing version. */}
      <IssueList issues={issues.filter((issue) => !issue.path.startsWith("phases["))} />
      {validating ? <p className="text-xs text-muted-foreground">{t("validating")}</p> : null}

      {selectedStep != null && selectedPhase != null ? (
        <Card>
          <CardContent className="flex flex-col gap-4 pt-5">
            <div className="flex flex-wrap items-center gap-2">
              <FieldTitle className="text-sm">
                {t("inspector", {
                  phase: selectedPhase.name ?? selectedPhase.id,
                  action: t(`action.${selectedStep.action}`),
                })}
              </FieldTitle>
              <div className="flex-1" />
              <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(null)}>
                {t("closeInspector")}
              </Button>
            </div>
            <StepInspector
              step={selectedStep}
              kind={kind}
              catalog={catalogQuery.data}
              catalogue={catalogue}
              disabled={!canManage}
              onChange={(patchStep) =>
                setRuleset({
                  ...ruleset,
                  phases: ruleset.phases.map((phase) =>
                    phase.id === selectedPhase.id
                      ? {
                          ...phase,
                          steps: phase.steps.map((step) =>
                            step.id === selectedStep.id ? { ...step, ...patchStep } : step
                          ),
                        }
                      : phase
                  ),
                })
              }
            />
          </CardContent>
        </Card>
      ) : null}

      <SeriesPreview
        tournamentId={tournamentId}
        kind={kind}
        mode={draft.mode}
        ruleset={ruleset}
        itemIds={draft.itemIds}
        slots={draft.slots.map((slot) => ({
          candidates: slot.candidates,
          reserve_item_id: slot.reserveItemId,
        }))}
        bestOf={series.bestOf}
      />
    </>
  );
}

/**
 * Whether this scope's ruleset still says what the scope above says, and one
 * click back to it. Inheritance is per CONFIG, not per field, so the whole
 * document is the unit that can be reset.
 */
function InheritedRuleset({
  scope,
  same,
  canManage,
  onReset,
}: Readonly<{ scope: string; same: boolean; canManage: boolean; onReset: () => void }>) {
  const t = useTranslations("pickBan.rules");

  if (same) {
    return <p className="text-xs text-muted-foreground">{t("sameAsScope", { scope })}</p>;
  }
  return (
    <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      <span>{t("overridesScope", { scope })}</span>
      {canManage ? (
        <Button type="button" variant="ghost" size="sm" className="h-6 px-2" onClick={onReset}>
          <RotateCcw aria-hidden className="me-1 size-3" />
          {t("useInherited")}
        </Button>
      ) : null}
    </p>
  );
}

/**
 * Export and import of the raw ruleset.
 *
 * The tournament's rules are drafted in a document and reviewed by people who
 * are not looking at this screen; pasting the JSON back is how a reviewed
 * ruleset lands without retyping a phase board.
 */
function JsonTransfer({
  ruleset,
  canManage,
  onImport,
}: Readonly<{
  ruleset: PickBanRuleset;
  canManage: boolean;
  onImport: (next: PickBanRuleset) => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [invalid, setInvalid] = useState(false);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          void navigator.clipboard?.writeText(JSON.stringify(ruleset, null, 2));
          notify.success(t("json.copied"));
        }}
      >
        <Download aria-hidden className="me-2 size-4" />
        {t("json.export")}
      </Button>

      {canManage ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            setText(JSON.stringify(ruleset, null, 2));
            setInvalid(false);
            setOpen(true);
          }}
        >
          <Upload aria-hidden className="me-2 size-4" />
          {t("json.import")}
        </Button>
      ) : null}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("json.importTitle")}</DialogTitle>
            <DialogDescription>{t("json.importHint")}</DialogDescription>
          </DialogHeader>
          <Textarea
            value={text}
            rows={18}
            className="font-mono text-xs"
            aria-label={t("json.importTitle")}
            aria-invalid={invalid}
            onChange={(event) => {
              setText(event.target.value);
              setInvalid(false);
            }}
          />
          {invalid ? (
            <Alert variant="destructive">
              <AlertDescription>{t("json.importFailed")}</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              {t("json.cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => {
                const parsed = parseRulesetJson(text);
                if (parsed == null) return setInvalid(true);
                onImport(parsed);
                setOpen(false);
              }}
            >
              <Check aria-hidden className="me-2 size-4" />
              {t("json.apply")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
