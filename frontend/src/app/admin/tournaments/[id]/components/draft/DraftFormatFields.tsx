"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { FieldDescription } from "@/components/ui/field";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { DraftFormat, DraftFormatSettings } from "@/types/draft.types";

import { DRAFT_ROUND_RULES } from "./setup-model";

interface DraftFormatFieldsProps {
  value: DraftFormatSettings;
  onChange: (next: DraftFormatSettings) => void;
  /** Off the tournament's roster shape: one rule per drafted round. */
  rounds: number;
  disabled?: boolean;
}

const FORMATS: DraftFormat[] = ["snake", "linear", "custom"];

/**
 * The tournament's draft format rule: snake, linear, or a rule per round. It
 * lives in the tournament settings, not the wizard — every draft of the
 * tournament is seeded with it server-side.
 */
export function DraftFormatFields({
  value,
  onChange,
  rounds,
  disabled = false
}: Readonly<DraftFormatFieldsProps>) {
  const t = useTranslations("draftAdmin");
  const formatLabelId = useId();
  const roundRulesLabelId = useId();

  const patch = (next: Partial<DraftFormatSettings>) => onChange({ ...value, ...next });
  // Rebuilt at the current round count so a shape change can never leave a hole
  // (serialized as null) in the payload.
  const roundRules = Array.from({ length: rounds }, (_, i) => value.round_rules[i] ?? "linear");

  return (
    <div className="space-y-3">
      <span id={formatLabelId} className="block text-sm font-medium leading-none">
        {t("format")}
      </span>
      <ToggleGroup
        variant="pill"
        size="sm"
        aria-labelledby={formatLabelId}
        value={value.format}
        onValueChange={(next) => patch({ format: next as DraftFormat })}
      >
        {FORMATS.map((format) => (
          <ToggleGroupItem key={format} value={format} disabled={disabled}>
            {t(`formats.${format}.title`)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <FieldDescription>{t(`formats.${value.format}.description`)}</FieldDescription>
      {value.format === "custom" && (
        <div className="space-y-3 border-t border-border pt-4">
          <div className="space-y-1">
            <span id={roundRulesLabelId} className="text-sm font-medium leading-none">
              {t("roundRules")}
            </span>
            <p className="text-xs text-muted-foreground">{t("roundRulesHint", { rounds })}</p>
          </div>
          {/* One labelled row per round, read top to bottom: a bare two-column
              grid of selects never said which round each rule belonged to, nor
              whether the flow was row- or column-major. */}
          <div className="space-y-2" role="group" aria-labelledby={roundRulesLabelId}>
            {roundRules.map((rule, index) => {
              const round = index + 1;
              const selectId = `draft-round-rule-${round}`;
              return (
                <div key={round} className="flex items-center gap-3">
                  <Label
                    htmlFor={selectId}
                    className="min-w-16 shrink-0 text-xs font-medium tabular-nums text-muted-foreground"
                  >
                    {t("roundNumber", { round })}
                  </Label>
                  <Select
                    disabled={disabled}
                    value={rule}
                    onValueChange={(next) => {
                      const nextRules = [...roundRules];
                      nextRules[index] = next;
                      patch({ round_rules: nextRules });
                    }}
                  >
                    <SelectTrigger id={selectId} className="flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DRAFT_ROUND_RULES.map((option) => (
                        <SelectItem key={option} value={option}>
                          {t(`rules.${option}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              );
            })}
          </div>
          {roundRules.some((rule) => rule.startsWith("team_avg_")) && (
            <div className="flex items-start justify-between gap-4 border-t border-border pt-3">
              <div>
                <Label htmlFor="draft-avg-tie-seed">{t("avgTieSeedReverse")}</Label>
                <p className="mt-1 text-xs text-muted-foreground">{t("avgTieSeedReverseHint")}</p>
              </div>
              <Switch
                id="draft-avg-tie-seed"
                disabled={disabled}
                checked={value.avg_tie_seed_reverse}
                onCheckedChange={(avg_tie_seed_reverse) => patch({ avg_tie_seed_reverse })}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
