"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
import {
  PICK_BAN_NO_REPEAT_SCOPES,
  PICK_BAN_ROTATIONS,
  protectHasNoStep,
  type PickBanDraft
} from "@/lib/tournament/pick-ban-config";
import type { PickBanFirstBanRotation, PickBanNoRepeatScope } from "@/types/tournament.types";

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

/** Step 3: the rules the draft runs under, and where each of them comes from. */
export function SidesStep({
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
