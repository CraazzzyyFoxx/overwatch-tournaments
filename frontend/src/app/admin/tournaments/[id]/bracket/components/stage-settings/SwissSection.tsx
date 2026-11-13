"use client";

import { Fragment, useId } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { Switch } from "@/components/ui/switch";
import { BEST_OF_OPTIONS } from "@/lib/tournament/best-of";

import { normalizeMaxRounds } from "@/lib/bracket/projection";
import type { SectionProps } from "./types";

/** What a threshold starts at when switched on: the CS Major's 3 wins / 3 losses. */
const DEFAULT_THRESHOLD = 3;

/**
 * Swiss auto-qualification and auto-elimination: a team whose result is
 * decided stops being paired. The server computes who is decided; this only
 * sets the thresholds and the series length of the match that decides them.
 */
export function SwissSection({ stage, form, onChange }: SectionProps) {
  const t = useTranslations("adminBracket.settings");
  const tRoot = useTranslations("adminBracket");
  const ids = useId();

  const thresholds = [
    {
      key: "qualify",
      value: form.swissQualifyWins,
      set: (next: number | null) => onChange({ swissQualifyWins: next }),
      bestOf: form.bestOf.swiss_qualify,
      setBestOf: (next: number | null) =>
        onChange({ bestOf: { ...form.bestOf, swiss_qualify: next } })
    },
    {
      key: "eliminate",
      value: form.swissEliminateLosses,
      set: (next: number | null) => onChange({ swissEliminateLosses: next }),
      bestOf: form.bestOf.swiss_eliminate,
      setBestOf: (next: number | null) =>
        onChange({ bestOf: { ...form.bestOf, swiss_eliminate: next } })
    }
  ] as const;

  const wins = form.swissQualifyWins;
  const losses = form.swissEliminateLosses;
  const rounds = normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5);
  // The longest road to a verdict: N-1 wins and M-1 losses, then the decider.
  const needed = wins != null && losses != null ? wins + losses - 1 : null;

  const warnings = needed != null && rounds < needed ? [t("swissRoundsShort", { needed, rounds })] : [];

  return (
    <SettingGroup id="stage-swiss" title={tRoot("editor.swiss")} description={t("swissHelp")}>
      {thresholds.map(({ key, value, set, bestOf, setBestOf }) => (
        <Fragment key={key}>
          <SettingRow htmlFor={`${ids}-${key}`} label={t(`${key}After`)} hint={t(`${key}AfterHelp`)}>
            <div className="flex items-center gap-3">
              {value != null ? (
                <NumberInput
                  id={`${ids}-${key}-count`}
                  aria-label={t(`${key}Count`)}
                  integer
                  min={1}
                  size="sm"
                  className="w-20"
                  value={value}
                  // Clearing the field is not "off" — the switch is. An empty
                  // field reverts to the last number on blur.
                  onValueChange={(next) => {
                    if (next != null) set(next);
                  }}
                />
              ) : null}
              <Switch
                id={`${ids}-${key}`}
                checked={value != null}
                onCheckedChange={(checked) => set(checked ? DEFAULT_THRESHOLD : null)}
              />
            </div>
          </SettingRow>

          {value != null ? (
            <SettingRow
              htmlFor={`${ids}-${key}-bo`}
              label={t(`${key}BestOf`)}
              hint={t(`${key}BestOfHelp`)}
            >
              <Select
                value={bestOf != null ? String(bestOf) : "none"}
                onValueChange={(next) => setBestOf(next === "none" ? null : Number(next))}
              >
                <SelectTrigger id={`${ids}-${key}-bo`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">
                    {t("regularBestOf", { bo: form.bestOf.default })}
                  </SelectItem>
                  {BEST_OF_OPTIONS.map((n) => (
                    <SelectItem key={n} value={String(n)}>{`Bo${n}`}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>
          ) : null}
        </Fragment>
      ))}

      {warnings.length > 0 ? (
        <div role="status" className="flex flex-col gap-1.5 py-3 last:pb-0">
          {warnings.map((warning) => (
            <p key={warning} className="flex items-start gap-1.5 text-caption text-warning">
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              <span className="min-w-0">{warning}</span>
            </p>
          ))}
        </div>
      ) : null}
    </SettingGroup>
  );
}
