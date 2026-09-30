"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
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
      <span id={formatLabelId} className="text-sm font-medium leading-none">
        {t("format")}
      </span>
      {/* radiogroup promises arrow-key traversal and a single tab stop, so the
          group owns the arrows and only the checked option stays tabbable. */}
      <div
        className="grid gap-3 md:grid-cols-3"
        role="radiogroup"
        aria-labelledby={formatLabelId}
        onKeyDown={(event) => {
          if (disabled) return;
          const delta =
            event.key === "ArrowRight" || event.key === "ArrowDown"
              ? 1
              : event.key === "ArrowLeft" || event.key === "ArrowUp"
                ? -1
                : 0;
          if (delta === 0) return;
          event.preventDefault();
          const index = Math.max(0, FORMATS.indexOf(value.format));
          const next = FORMATS[(index + delta + FORMATS.length) % FORMATS.length];
          patch({ format: next });
          event.currentTarget.querySelector<HTMLButtonElement>(`[data-format="${next}"]`)?.focus();
        }}
      >
        {FORMATS.map((format) => (
          <button
            key={format}
            type="button"
            role="radio"
            data-format={format}
            tabIndex={value.format === format ? 0 : -1}
            aria-checked={value.format === format}
            disabled={disabled}
            onClick={() => patch({ format })}
            className={cn(
              "rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              value.format === format
                ? "border-primary bg-primary/8 ring-1 ring-primary/30"
                : "border-border/70 bg-card hover:border-primary/40"
            )}
          >
            <span className="font-medium">{t(`formats.${format}.title`)}</span>
            <span className="mt-1 block text-xs text-muted-foreground">
              {t(`formats.${format}.description`)}
            </span>
            <span className="mt-3 flex gap-1" aria-hidden>
              {[1, 2, 3, 4].map((seat, index) => (
                <span
                  key={seat}
                  className={cn(
                    "grid h-6 w-6 place-items-center rounded-md bg-muted text-xs font-semibold tabular-nums",
                    format === "snake" && index > 1 && "bg-primary/15 text-primary"
                  )}
                >
                  {format === "snake" && index > 1 ? 5 - seat : seat}
                </span>
              ))}
            </span>
          </button>
        ))}
      </div>
      {value.format === "custom" && (
        <div className="space-y-3 rounded-xl border border-border/70 bg-muted/20 p-4">
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
            <div className="flex items-start justify-between gap-4 border-t border-border/60 pt-3">
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
