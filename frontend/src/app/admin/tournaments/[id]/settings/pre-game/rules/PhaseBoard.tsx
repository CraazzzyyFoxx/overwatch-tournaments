"use client";

import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp, Copy, Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  PICK_BAN_STEP_TEMPLATES,
  addStep,
  duplicatePhase,
  duplicateStep,
  movePhase,
  moveStep,
  newPhase,
  removePhase,
  removeStep,
  stepLifetimeSummary,
  stepSummary,
  updatePhase,
  type PickBanStepTemplate,
} from "@/lib/tournament/pick-ban-config";
import type {
  PickBanGenerator,
  PickBanKind,
  PickBanRuleset,
  PickBanRulesCatalog,
  PickBanRulesIssue,
  PickBanRulesetPhase,
  PickBanRulesetStep,
} from "@/types/tournament.types";

import type { CatalogueItem } from "../CataloguePicker";
import { ConditionField } from "./ConditionField";
import { IssueList } from "./IssueList";

const GENERATOR_NONE = "__none__";

/** One phase's position in the issue paths the validator returns. */
const phasePath = (index: number) => `phases[${index}]`;

/**
 * The phase board: one card per phase, each holding its ordered steps.
 *
 * A phase is "which steps run on which map of the series" — the `when` chip is
 * the condition that decides, and the first phase whose condition matches the
 * round wins. That ordering is why phases move up and down rather than living
 * in a set.
 */
export function PhaseBoard({
  ruleset,
  kind,
  catalog,
  catalogue,
  issues,
  selected,
  canManage,
  onChange,
  onSelect,
}: Readonly<{
  ruleset: PickBanRuleset;
  kind: PickBanKind;
  catalog: PickBanRulesCatalog | undefined;
  catalogue: CatalogueItem[];
  issues: PickBanRulesIssue[];
  selected: { phaseId: string; stepId: string } | null;
  canManage: boolean;
  onChange: (next: PickBanRuleset) => void;
  onSelect: (selection: { phaseId: string; stepId: string } | null) => void;
}>) {
  const t = useTranslations("pickBan.rules");

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 lg:grid-cols-2">
        {ruleset.phases.map((phase, index) => (
          <PhaseCard
            key={phase.id}
            phase={phase}
            index={index}
            total={ruleset.phases.length}
            kind={kind}
            catalog={catalog}
            catalogue={catalogue}
            issues={issues.filter((issue) => issue.path.startsWith(phasePath(index)))}
            pathPrefix={phasePath(index)}
            selected={selected}
            canManage={canManage}
            onChange={onChange}
            ruleset={ruleset}
            onSelect={onSelect}
          />
        ))}
      </div>

      {canManage ? (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-dashed"
            onClick={() =>
              onChange({ ...ruleset, phases: [...ruleset.phases, newPhase(ruleset)] })
            }
          >
            <Plus aria-hidden className="me-2 size-4" />
            {t("phase.add")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function PhaseCard({
  phase,
  index,
  total,
  kind,
  catalog,
  catalogue,
  issues,
  pathPrefix,
  selected,
  canManage,
  ruleset,
  onChange,
  onSelect,
}: Readonly<{
  phase: PickBanRulesetPhase;
  index: number;
  total: number;
  kind: PickBanKind;
  catalog: PickBanRulesCatalog | undefined;
  catalogue: CatalogueItem[];
  issues: PickBanRulesIssue[];
  pathPrefix: string;
  selected: { phaseId: string; stepId: string } | null;
  canManage: boolean;
  ruleset: PickBanRuleset;
  onChange: (next: PickBanRuleset) => void;
  onSelect: (selection: { phaseId: string; stepId: string } | null) => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const generated = phase.generator != null;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs tabular-nums text-muted-foreground">{index + 1}</span>
          <Input
            className="h-8 max-w-52 text-sm"
            value={phase.name ?? ""}
            disabled={!canManage}
            aria-label={t("phase.name", { n: index + 1 })}
            placeholder={t("phase.namePlaceholder")}
            onChange={(event) =>
              onChange(updatePhase(ruleset, phase.id, { name: event.target.value || null }))
            }
          />
          <div className="flex-1" />
          {canManage ? (
            <div className="flex items-center gap-0.5">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={index === 0}
                aria-label={t("phase.moveUp", { n: index + 1 })}
                onClick={() => onChange(movePhase(ruleset, phase.id, -1))}
              >
                <ArrowUp aria-hidden className="size-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={index === total - 1}
                aria-label={t("phase.moveDown", { n: index + 1 })}
                onClick={() => onChange(movePhase(ruleset, phase.id, 1))}
              >
                <ArrowDown aria-hidden className="size-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label={t("phase.duplicate", { n: index + 1 })}
                onClick={() => onChange(duplicatePhase(ruleset, phase.id))}
              >
                <Copy aria-hidden className="size-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={total === 1}
                aria-label={t("phase.remove", { n: index + 1 })}
                onClick={() => onChange(removePhase(ruleset, phase.id))}
              >
                <Trash2 aria-hidden className="size-4 text-destructive" />
              </Button>
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <ConditionField
            label={t("phase.when")}
            description={t("phase.whenHint")}
            value={phase.when}
            context="round"
            kind={kind}
            catalog={catalog}
            catalogue={catalogue}
            disabled={!canManage}
            onChange={(next) => onChange(updatePhase(ruleset, phase.id, { when: next }))}
          />
          <ConditionField
            label={t("phase.poolFilter")}
            description={t("phase.poolFilterHint")}
            value={phase.pool_filter}
            context="pool"
            kind={kind}
            catalog={catalog}
            catalogue={catalogue}
            disabled={!canManage}
            onChange={(next) => onChange(updatePhase(ruleset, phase.id, { pool_filter: next }))}
          />
        </div>

        {/* Only a map veto has a shape the server can generate: banning a pool
            down to the maps a series plays. A hero pool stays playable. */}
        {kind === "map" ? (
          <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {t("phase.generator")}
            <Select
              value={phase.generator ?? GENERATOR_NONE}
              disabled={!canManage}
              onValueChange={(value) =>
                onChange(
                  updatePhase(ruleset, phase.id, {
                    generator: value === GENERATOR_NONE ? null : (value as PickBanGenerator),
                    // A generated phase expands server-side; hand-written steps
                    // would never run, so they are dropped rather than hidden.
                    steps: value === GENERATOR_NONE ? phase.steps : [],
                  })
                )
              }
            >
              <SelectTrigger className="h-7 w-48 text-xs">
                {t(`phase.generatorValue.${phase.generator ?? "none"}`)}
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={GENERATOR_NONE}>{t("phase.generatorValue.none")}</SelectItem>
                <SelectItem value="bracket">{t("phase.generatorValue.bracket")}</SelectItem>
                <SelectItem value="slot_veto">{t("phase.generatorValue.slot_veto")}</SelectItem>
              </SelectContent>
            </Select>
          </label>
        ) : null}

        {generated ? (
          <p className="text-xs text-muted-foreground">{t("phase.generatedHint")}</p>
        ) : (
          <>
            <ol className="flex flex-col gap-1.5">
              {phase.steps.map((step, stepIndex) => (
                <li key={step.id}>
                  <StepCard
                    step={step}
                    index={stepIndex}
                    total={phase.steps.length}
                    issues={issues.filter((issue) =>
                      issue.path.startsWith(`${pathPrefix}.steps[${stepIndex}]`)
                    )}
                    selected={selected?.phaseId === phase.id && selected.stepId === step.id}
                    canManage={canManage}
                    onSelect={() => onSelect({ phaseId: phase.id, stepId: step.id })}
                    onMove={(delta) => onChange(moveStep(ruleset, phase.id, step.id, delta))}
                    onDuplicate={() => onChange(duplicateStep(ruleset, phase.id, step.id))}
                    onRemove={() => {
                      if (selected?.stepId === step.id) onSelect(null);
                      onChange(removeStep(ruleset, phase.id, step.id));
                    }}
                  />
                </li>
              ))}
            </ol>

            {phase.steps.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("phase.noSteps")}</p>
            ) : null}

            {canManage ? (
              <StepPalette
                onAdd={(template) => {
                  const next = addStep(ruleset, phase.id, template);
                  const created = next.phases.find((one) => one.id === phase.id)?.steps.at(-1);
                  onChange(next);
                  if (created) onSelect({ phaseId: phase.id, stepId: created.id });
                }}
              />
            ) : null}
          </>
        )}

        {/* Issues whose path names the phase itself, not one of its steps. */}
        <IssueList issues={issues.filter((issue) => !issue.path.includes(".steps["))} />
      </CardContent>
    </Card>
  );
}

function StepCard({
  step,
  index,
  total,
  issues,
  selected,
  canManage,
  onSelect,
  onMove,
  onDuplicate,
  onRemove,
}: Readonly<{
  step: PickBanRulesetStep;
  index: number;
  total: number;
  issues: PickBanRulesIssue[];
  selected: boolean;
  canManage: boolean;
  onSelect: () => void;
  onMove: (delta: number) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const summary = stepSummary(step);
  const lifetime = stepLifetimeSummary(step);
  const hasError = issues.some((issue) => issue.severity === "error");

  return (
    <div
      className={cn(
        "rounded-md border bg-card p-2",
        selected ? "border-primary ring-1 ring-primary" : "border-border",
        hasError && "border-destructive"
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSelect}
          aria-pressed={selected}
          className="flex min-w-0 flex-1 items-center gap-2 text-start"
        >
          <span className="text-xs tabular-nums text-muted-foreground">{index + 1}</span>
          <span className="truncate text-sm font-medium">
            {t(`action.${step.action}`)} · {t(`actors.${step.actors}`)}
          </span>
          <Badge variant="secondary" className="shrink-0">
            {t(`summary.${summary.key}`, summary.values)}
          </Badge>
          {lifetime == null ? null : (
            <Badge variant="outline" className="shrink-0">
              {t(`summary.${lifetime.key}`, lifetime.values)}
            </Badge>
          )}
        </button>
        {canManage ? (
          <div className="flex items-center gap-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              disabled={index === 0}
              aria-label={t("step.moveUp", { n: index + 1 })}
              onClick={() => onMove(-1)}
            >
              <ArrowUp aria-hidden className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              disabled={index === total - 1}
              aria-label={t("step.moveDown", { n: index + 1 })}
              onClick={() => onMove(1)}
            >
              <ArrowDown aria-hidden className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={t("step.duplicate", { n: index + 1 })}
              onClick={onDuplicate}
            >
              <Copy aria-hidden className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={t("step.remove", { n: index + 1 })}
              onClick={onRemove}
            >
              <Trash2 aria-hidden className="size-4 text-destructive" />
            </Button>
          </div>
        ) : null}
      </div>
      <IssueList issues={issues} />
    </div>
  );
}

/** The step shapes the palette offers, each a preconfigured real step. */
function StepPalette({ onAdd }: Readonly<{ onAdd: (template: PickBanStepTemplate) => void }>) {
  const t = useTranslations("pickBan.rules");

  return (
    <div className="flex flex-wrap gap-1.5">
      {PICK_BAN_STEP_TEMPLATES.map((template) => (
        <Button
          key={template}
          type="button"
          variant="outline"
          size="sm"
          className="h-7 border-dashed text-xs font-normal"
          title={t(`template.${template}.hint`)}
          onClick={() => onAdd(template)}
        >
          <Plus aria-hidden className="size-3.5" />
          {t(`template.${template}.label`)}
        </Button>
      ))}
    </div>
  );
}
