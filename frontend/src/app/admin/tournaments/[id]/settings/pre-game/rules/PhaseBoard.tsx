"use client";

import { useTranslations } from "next-intl";
import { ArrowDown, ArrowUp, Copy, MoreHorizontal, Plus } from "lucide-react";

import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { RowButton } from "@/components/ui/row-button";
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
  actorsMessageKey,
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
 * The phase board: one section per phase, each holding its ordered steps.
 *
 * A phase is "which steps run on which map of the series": the `when` chip is
 * the condition that decides, and the first phase whose condition matches the
 * round wins. That ordering is why phases are dragged into order rather than
 * living in a set.
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
      <SortableRows
        className="flex flex-col divide-y divide-border"
        items={ruleset.phases}
        getId={(phase) => phase.id}
        onReorder={(phases) => onChange({ ...ruleset, phases })}
      >
        {(phase, index) => (
          <PhaseSection
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
        )}
      </SortableRows>

      {canManage ? (
        <div>
          <Button
            type="button"
            variant="dashed"
            size="sm"
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

/**
 * The actions of a phase or a step: reorder and duplicate one click away,
 * delete in the menu. When delete is impossible the item stays, disabled,
 * with the reason under it.
 */
function RowActions({
  scope,
  index,
  total,
  removeBlockedReason,
  onMove,
  onDuplicate,
  onRemove,
}: Readonly<{
  scope: "phase" | "step";
  index: number;
  total: number;
  removeBlockedReason?: string;
  onMove: (delta: -1 | 1) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const n = index + 1;
  const moveUp = t(`${scope}.moveUp`, { n });
  const moveDown = t(`${scope}.moveDown`, { n });
  const duplicate = t(`${scope}.duplicate`, { n });
  const actions = t(`${scope}.actions`, { n });

  return (
    <div className="flex shrink-0 items-center gap-0.5">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7"
        disabled={index === 0}
        aria-label={moveUp}
        title={moveUp}
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
        aria-label={moveDown}
        title={moveDown}
        onClick={() => onMove(1)}
      >
        <ArrowDown aria-hidden className="size-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7"
        aria-label={duplicate}
        title={duplicate}
        onClick={onDuplicate}
      >
        <Copy aria-hidden className="size-4" />
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={actions}
            title={actions}
          >
            <MoreHorizontal aria-hidden className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            variant="destructive"
            disabled={removeBlockedReason != null}
            onSelect={onRemove}
          >
            <span>
              {t("rowMenu.remove")}
              {removeBlockedReason == null ? null : (
                <span className="block text-caption text-muted-foreground">
                  {removeBlockedReason}
                </span>
              )}
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function PhaseSection({
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
  const { ref, style, handleProps } = useSortableRow(phase.id, !canManage);
  const generated = phase.generator != null;

  return (
    <section
      ref={ref}
      style={style}
      className="flex flex-col gap-3 bg-card py-4 first:pt-0 last:pb-0"
    >
      <div className="flex flex-wrap items-center gap-2">
        {canManage && total > 1 ? (
          <SortableGrip handleProps={handleProps} label={t("phase.reorder", { n: index + 1 })} />
        ) : null}
        <span className="text-xs tabular-nums text-muted-foreground">{index + 1}</span>
        <Input
          size="sm"
          className="max-w-52"
          value={phase.name ?? ""}
          disabled={!canManage}
          aria-label={t("phase.name", { n: index + 1 })}
          onChange={(event) =>
            onChange(updatePhase(ruleset, phase.id, { name: event.target.value || null }))
          }
        />
        <div className="flex-1" />
        {canManage ? (
          <RowActions
            scope="phase"
            index={index}
            total={total}
            removeBlockedReason={total > 1 ? undefined : t("rowMenu.lastPhase")}
            onMove={(delta) => onChange(movePhase(ruleset, phase.id, delta))}
            onDuplicate={() => onChange(duplicatePhase(ruleset, phase.id))}
            onRemove={() => onChange(removePhase(ruleset, phase.id))}
          />
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
            <SelectTrigger size="sm" className="h-7 w-48">
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
          {phase.steps.length > 0 ? (
            <SortableRows
              className="flex flex-col divide-y divide-border"
              items={phase.steps}
              getId={(step) => step.id}
              onReorder={(steps) => onChange(updatePhase(ruleset, phase.id, { steps }))}
            >
              {(step, stepIndex) => (
                <StepRow
                  key={step.id}
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
              )}
            </SortableRows>
          ) : (
            <p className="text-xs text-muted-foreground">{t("phase.noSteps")}</p>
          )}

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
    </section>
  );
}

function StepRow({
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
  onMove: (delta: -1 | 1) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const { ref, style, handleProps } = useSortableRow(step.id, !canManage);
  const summary = stepSummary(step);
  const lifetime = stepLifetimeSummary(step);
  const hasError = issues.some((issue) => issue.severity === "error");

  return (
    <div
      ref={ref}
      style={style}
      className={cn("rounded-md bg-card px-1 py-1.5", selected && "bg-accent/40")}
    >
      <div className="flex items-center gap-2">
        {canManage && total > 1 ? (
          <SortableGrip handleProps={handleProps} label={t("step.reorder", { n: index + 1 })} />
        ) : null}
        <RowButton
          onClick={onSelect}
          aria-pressed={selected}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-sm"
        >
          <span className="text-xs tabular-nums text-muted-foreground">{index + 1}</span>
          <span className={cn("truncate text-sm font-medium", hasError && "text-danger")}>
            {t(`action.${step.action}`)} · {t(`actors.${actorsMessageKey(step.actors)}`)}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            · {t(`summary.${summary.key}`, summary.values)}
          </span>
          {lifetime == null ? null : (
            <span className="shrink-0 text-xs text-muted-foreground">
              · {t(`summary.${lifetime.key}`, lifetime.values)}
            </span>
          )}
        </RowButton>
        {canManage ? (
          <RowActions
            scope="step"
            index={index}
            total={total}
            onMove={onMove}
            onDuplicate={onDuplicate}
            onRemove={onRemove}
          />
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
          variant="dashed"
          size="xs"
          title={t(`template.${template}.hint`)}
          onClick={() => onAdd(template)}
        >
          <Plus aria-hidden />
          {t(`template.${template}.label`)}
        </Button>
      ))}
    </div>
  );
}
