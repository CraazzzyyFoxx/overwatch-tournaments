"use client";

import type { ComponentType, ReactNode } from "react";
import { useTranslations } from "next-intl";

import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { FEED_MODES, type FeedMode, type FeedRule } from "@/lib/flow/stageFeed";
import type { Stage, StageType } from "@/types/tournament.types";

/** One labelled control; the stage editor draws it as a `SettingRow`, the add-stage dialog as a stacked field. */
export type FeedField = ComponentType<{ id: string; label: string; hint?: string; children: ReactNode }>;

/** The modes `source` can feed under; `current` stays listed so an existing rule never renders blank. */
export function modesFor(source: Pick<Stage, "items" | "stage_type">, current?: FeedMode): FeedMode[] {
  return FEED_MODES.filter(
    (mode) =>
      mode === current ||
      mode === "all" ||
      mode === "top" ||
      (mode === "per_item_top"
        ? source.items.length > 1
        : source.stage_type === "swiss" || source.stage_type === "individual_swiss")
  );
}

/** The rule of who advances out of `source`: mode, count, upper-bracket split, Swiss status. */
export function FeedRuleFields({
  ids,
  rule,
  source,
  targetStageType,
  disabled,
  Field,
  onChange
}: Readonly<{
  ids: string;
  rule: FeedRule;
  source: Pick<Stage, "items" | "stage_type">;
  /** Null when the rule feeds a formation, which has no bracket to split. */
  targetStageType: StageType | null;
  disabled?: boolean;
  Field: FeedField;
  onChange: (patch: Partial<FeedRule>) => void;
}>) {
  const t = useTranslations("adminBracket.feed");
  const counted = rule.mode === "top" || rule.mode === "per_item_top";

  return (
    <>
      <Field id={`${ids}-rule`} label={t("rule")}>
        <Select value={rule.mode} disabled={disabled} onValueChange={(mode) => onChange({ mode: mode as FeedMode })}>
          <SelectTrigger id={`${ids}-rule`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {modesFor(source, rule.mode).map((mode) => (
              <SelectItem key={mode} value={mode}>
                {t(`modes.${mode}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {counted ? (
        <Field id={`${ids}-n`} label={rule.mode === "top" ? t("countTop") : t("countPerGroup")}>
          <NumberInput
            id={`${ids}-n`}
            integer
            min={1}
            size="sm"
            className="w-24"
            disabled={disabled}
            value={rule.n}
            // An empty field is a pause in typing, not a rule: it reverts to the last number on blur.
            onValueChange={(n) => {
              if (n != null) onChange({ n });
            }}
          />
        </Field>
      ) : null}

      {counted && targetStageType === "double_elimination" ? (
        <Field id={`${ids}-upper`} label={rule.mode === "top" ? t("upperTop") : t("upper")} hint={t("upperHint")}>
          <NumberInput
            id={`${ids}-upper`}
            integer
            min={0}
            size="sm"
            className="w-24"
            disabled={disabled}
            value={rule.upper}
            onValueChange={(upper) => onChange({ upper })}
          />
        </Field>
      ) : null}

      {rule.mode === "swiss_status" ? (
        <Field id={`${ids}-status`} label={t("swissStatus")}>
          <Select
            value={rule.swissStatus}
            disabled={disabled}
            onValueChange={(swissStatus) => onChange({ swissStatus: swissStatus as FeedRule["swissStatus"] })}
          >
            <SelectTrigger id={`${ids}-status`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="qualified">{t("qualified")}</SelectItem>
              <SelectItem value="eliminated">{t("eliminated")}</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      ) : null}
    </>
  );
}
