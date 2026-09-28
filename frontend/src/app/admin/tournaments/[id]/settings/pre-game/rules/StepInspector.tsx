"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  PICK_BAN_ACTORS,
  PICK_BAN_STEP_ACTIONS,
  PICK_BAN_TIMEOUTS,
} from "@/lib/tournament/pick-ban-config";
import type {
  PickBanActors,
  PickBanConstraint,
  PickBanKind,
  PickBanRulesCatalog,
  PickBanRulesetStep,
  PickBanStepAction,
  PickBanTimeoutPolicy,
} from "@/types/tournament.types";

import type { CatalogueItem } from "../CataloguePicker";
import { ConditionField } from "./ConditionField";
import { ParamFields } from "./ParamFields";

/** Radix rejects an empty `<SelectItem>` value; "inherit"/"none" are real choices. */
const INHERIT = "__inherit__";
const NONE = "__none__";

/**
 * Every parameter of one step (§1), in the order an organizer reasons about
 * them: who acts, how much, how, and what they may take.
 *
 * A step is the unit the room actually runs, so this is deliberately the one
 * dense surface of the constructor rather than a wizard — an organizer tuning
 * "five bans each, blind, one per opponent player" is changing four fields of
 * the same thing.
 */
export function StepInspector({
  step,
  kind,
  catalog,
  catalogue,
  disabled,
  onChange,
}: Readonly<{
  step: PickBanRulesetStep;
  kind: PickBanKind;
  catalog: PickBanRulesCatalog | undefined;
  catalogue: CatalogueItem[];
  disabled?: boolean;
  onChange: (patch: Partial<PickBanRulesetStep>) => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const ids = useId();
  const isBan = step.action === "ban";
  const groups = catalog?.groups?.[kind] ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor={`${ids}-action`}>{t("step.action")}</FieldLabel>
          <Select
            value={step.action}
            disabled={disabled}
            onValueChange={(value) =>
              onChange({
                action: value as PickBanStepAction,
                // Only a ban expires; a decider is always the engine's roll.
                lifetime: value === "ban" ? (step.lifetime ?? 1) : null,
                actors: value === "decider" ? "system" : step.actors,
              })
            }
          >
            <SelectTrigger id={`${ids}-action`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_STEP_ACTIONS.map((action) => (
                <SelectItem key={action} value={action}>
                  {t(`action.${action}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-actors`}>{t("step.actors")}</FieldLabel>
          <Select
            value={step.actors}
            disabled={disabled}
            onValueChange={(value) => onChange({ actors: value as PickBanActors })}
          >
            <SelectTrigger id={`${ids}-actors`} aria-describedby={`${ids}-actors-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PICK_BAN_ACTORS.map((actors) => (
                <SelectItem key={actors} value={actors}>
                  {t(`actors.${actors}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription id={`${ids}-actors-hint`}>
            {t(`actorsHint.${step.actors}`)}
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-count`}>{t("step.count")}</FieldLabel>
          <NumberInput
            id={`${ids}-count`}
            className="w-24"
            integer
            min={1}
            max={20}
            disabled={disabled}
            value={step.count}
            onValueChange={(value) => onChange({ count: value ?? 1 })}
          />
          <FieldDescription>{t("step.countHint")}</FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-min`}>{t("step.min")}</FieldLabel>
          <NumberInput
            id={`${ids}-min`}
            className="w-24"
            integer
            min={0}
            max={step.count}
            disabled={disabled}
            placeholder={t("step.minAuto")}
            value={step.min}
            onValueChange={(value) => onChange({ min: value })}
          />
          <FieldDescription>{t("step.minHint")}</FieldDescription>
        </Field>
      </div>

      <Field orientation="horizontal">
        <Switch
          id={`${ids}-blind`}
          checked={step.blind}
          disabled={disabled}
          onCheckedChange={(checked) => onChange({ blind: checked })}
        />
        <FieldContent>
          <FieldLabel htmlFor={`${ids}-blind`}>{t("step.blind")}</FieldLabel>
          <FieldDescription>{t("step.blindHint")}</FieldDescription>
        </FieldContent>
      </Field>

      {kind === "hero" ? (
        <Field orientation="horizontal">
          <Switch
            id={`${ids}-target`}
            checked={step.target != null}
            disabled={disabled}
            onCheckedChange={(checked) =>
              onChange({ target: checked ? "opponent_player" : null })
            }
          />
          <FieldContent>
            <FieldLabel htmlFor={`${ids}-target`}>{t("step.target")}</FieldLabel>
            <FieldDescription>{t("step.targetHint")}</FieldDescription>
          </FieldContent>
        </Field>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {isBan ? (
          <Field>
            <FieldLabel htmlFor={`${ids}-lifetime`}>{t("step.lifetime")}</FieldLabel>
            <NumberInput
              id={`${ids}-lifetime`}
              className="w-24"
              integer
              min={1}
              disabled={disabled}
              placeholder={t("step.lifetimeSeries")}
              value={step.lifetime}
              onValueChange={(value) => onChange({ lifetime: value })}
            />
            <FieldDescription>{t("step.lifetimeHint")}</FieldDescription>
          </Field>
        ) : null}

        <Field>
          <FieldLabel htmlFor={`${ids}-timer`}>{t("step.timer")}</FieldLabel>
          <NumberInput
            id={`${ids}-timer`}
            className="w-28"
            integer
            min={5}
            disabled={disabled}
            placeholder={t("step.timerInherit")}
            value={step.timer_seconds}
            onValueChange={(value) => onChange({ timer_seconds: value })}
          />
          <FieldDescription>{t("step.timerHint")}</FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-timeout`}>{t("step.onTimeout")}</FieldLabel>
          <Select
            value={step.on_timeout ?? INHERIT}
            disabled={disabled}
            onValueChange={(value) =>
              onChange({ on_timeout: value === INHERIT ? null : (value as PickBanTimeoutPolicy) })
            }
          >
            <SelectTrigger id={`${ids}-timeout`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={INHERIT}>{t("step.onTimeoutInherit")}</SelectItem>
              {PICK_BAN_TIMEOUTS.map((policy) => (
                <SelectItem key={policy} value={policy}>
                  {t(`onTimeout.${policy}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field>
          <FieldLabel htmlFor={`${ids}-dispute`}>{t("step.disputeMax")}</FieldLabel>
          <div className="flex items-center gap-2">
            <Switch
              id={`${ids}-dispute`}
              checked={step.dispute.enabled}
              disabled={disabled}
              onCheckedChange={(checked) =>
                onChange({
                  dispute: { enabled: checked, max: checked ? Math.max(1, step.dispute.max) : 0 },
                })
              }
            />
            <NumberInput
              className="w-20"
              integer
              min={0}
              max={5}
              aria-label={t("step.disputeMax")}
              disabled={disabled || !step.dispute.enabled}
              value={step.dispute.max}
              onValueChange={(value) =>
                onChange({ dispute: { ...step.dispute, max: value ?? 0 } })
              }
            />
          </div>
          <FieldDescription>{t("step.disputeHint")}</FieldDescription>
        </Field>
      </div>

      <ConditionField
        label={t("step.eligible")}
        description={t("step.eligibleHint")}
        value={step.eligible}
        context="item"
        kind={kind}
        catalog={catalog}
        catalogue={catalogue}
        hasTarget={step.target != null}
        disabled={disabled}
        onChange={(next) => onChange({ eligible: next })}
      />

      <ConstraintList
        constraints={step.constraints}
        kind={kind}
        catalog={catalog}
        catalogue={catalogue}
        groups={groups}
        hasTarget={step.target != null}
        disabled={disabled}
        onChange={(next) => onChange({ constraints: next })}
      />
    </div>
  );
}

/**
 * The step's constraints (§2), built from the catalog's specs.
 *
 * Constraints are checked on every submission rather than filtering the board,
 * which is why they are a list of their own and not more condition leaves: "at
 * most one hero per role" is a statement about the whole submission, and no
 * per-item predicate can express it.
 */
function ConstraintList({
  constraints,
  kind,
  catalog,
  catalogue,
  groups,
  hasTarget,
  disabled,
  onChange,
}: Readonly<{
  constraints: PickBanConstraint[];
  kind: PickBanKind;
  catalog: PickBanRulesCatalog | undefined;
  catalogue: CatalogueItem[];
  groups: string[];
  hasTarget: boolean;
  disabled?: boolean;
  onChange: (next: PickBanConstraint[]) => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const specs = (catalog?.constraints ?? []).filter(
    (spec) => hasTarget || !spec.requires_target
  );

  const constraintLabel = (type: string) => {
    const key = `constraint.${type}` as "constraint.one_per_target";
    return t.has(key) ? t(key) : type;
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">{t("step.constraints")}</p>
        <Select
          value={NONE}
          disabled={disabled || specs.length === 0}
          onValueChange={(type) => onChange([...constraints, { type, params: {} }])}
        >
          <SelectTrigger className="h-7 w-48 text-xs" aria-label={t("step.addConstraint")}>
            <span className="flex items-center gap-1.5">
              <Plus aria-hidden className="size-3.5" />
              {t("step.addConstraint")}
            </span>
          </SelectTrigger>
          <SelectContent>
            {specs.map((spec) => (
              <SelectItem key={spec.type} value={spec.type}>
                {constraintLabel(spec.type)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {constraints.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("step.noConstraints")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {constraints.map((constraint, index) => {
            const spec = specs.find((candidate) => candidate.type === constraint.type);
            return (
              <li
                key={`${constraint.type}-${index}`}
                className="rounded-md border border-border bg-card p-2"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium">{constraintLabel(constraint.type)}</span>
                  <div className="flex-1" />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6"
                    disabled={disabled}
                    aria-label={t("step.removeConstraint", {
                      constraint: constraintLabel(constraint.type),
                    })}
                    onClick={() => onChange(constraints.filter((_, at) => at !== index))}
                  >
                    <Trash2 aria-hidden className="size-3.5 text-destructive" />
                  </Button>
                </div>
                <ParamFields
                  specs={spec?.params ?? []}
                  params={constraint.params}
                  setParam={(key, value) =>
                    onChange(
                      constraints.map((existing, at) =>
                        at === index
                          ? { ...existing, params: { ...existing.params, [key]: value } }
                          : existing
                      )
                    )
                  }
                  controlName={(field) => `${field} · ${constraintLabel(constraint.type)}`}
                  kind={kind}
                  groups={groups}
                  catalogue={catalogue}
                  disabled={disabled}
                />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
