"use client";

import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { PICK_BAN_ROTATIONS, type PickBanDraft } from "@/lib/tournament/pick-ban-config";
import type { PickBanFirstBanRotation } from "@/types/tournament.types";

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

/**
 * Step 3: who opens the pick-ban, and how that alternates down the series.
 *
 * Everything about HOW a round is played moved into the ruleset (step 2); what
 * is left here is the one thing no step can decide for itself — which side the
 * ruleset's `first` actor resolves to on each map.
 */
export function SidesStep({
  ids,
  draft,
  inherited,
  inheritedLabel,
  canManage,
  patch
}: Readonly<{
  ids: string;
  draft: PickBanDraft;
  /** Rules of the scope above, or null at the tournament level. */
  inherited: PickBanDraft | null;
  inheritedLabel: string | null;
  canManage: boolean;
  patch: (values: Partial<PickBanDraft>) => void;
}>) {
  const t = useTranslations("pickBan.admin");

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
          <FieldTitle className="text-sm">{t("firstPickRule")}</FieldTitle>
          {/* One enum member exists server-side, so a control here would be a
              choice with nothing to choose. Stated instead of offered. */}
          <p className="text-sm font-medium">{t("firstPickRuleValue.higher_seed")}</p>
          <FieldDescription>{t("firstPickRuleHint")}</FieldDescription>
        </Field>
      </div>
    </>
  );
}
