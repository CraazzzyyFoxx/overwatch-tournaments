"use client";

import { useId, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { tiebreakersForStageType } from "@/lib/tournament/tiebreakers";
import type { StagePairingMode, StageType } from "@/types/tournament.types";

import { defaultTiebreakOrder, STAGE_TYPE_LABELS } from "@/lib/bracket/projection";
import type { SectionProps } from "./types";

/** `children`: more rows of the stage's basics, after its own (where its participants come from). */
export function GeneralSection({
  stage,
  form,
  onChange,
  isSuperuser,
  children
}: SectionProps & { isSuperuser: boolean; children?: ReactNode }) {
  const t = useTranslations("adminBracket.settings");
  const tRoot = useTranslations("adminBracket");
  const ids = useId();

  // Why the format cannot change, said where the disabled control is.
  const formatHint =
    [stage.has_custom_bracket ? t("resetCustom") : null, isSuperuser ? null : t("superuserOnly")]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <SettingGroup id="stage-general" title={tRoot("editor.general")}>
      <SettingRow htmlFor={`${ids}-name`} label={t("name")} stacked>
        <Input
          id={`${ids}-name`}
          value={form.name}
          onChange={(event) => onChange({ name: event.target.value })}
        />
      </SettingRow>

      <SettingRow htmlFor={`${ids}-type`} label={t("format")} hint={formatHint}>
        <Select
          value={form.stageType}
          onValueChange={(value) => {
            const stageType = value as StageType;
            // The metric catalogues are disjoint across families: an FFA
            // order on a duel stage (or the other way round) is one the
            // engine silently drops, so the new format's default replaces it
            // rather than being saved as an order nothing evaluates.
            const catalogue = tiebreakersForStageType(stageType, form.ffaColumns).map(
              (metric) => metric.id
            );
            const runnable = form.tiebreakOrder.every((metricId) =>
              (catalogue as string[]).includes(metricId)
            );
            onChange(
              runnable
                ? { stageType }
                : {
                    stageType,
                    rankingPreset: "default",
                    tiebreakOrder: defaultTiebreakOrder(stageType, form.ffaColumns)
                  }
            );
          }}
          // A drawn template is a bracket of one shape: switching format
          // would leave the stage with a layout its engine cannot generate.
          disabled={!isSuperuser || stage.has_custom_bracket}
        >
          <SelectTrigger id={`${ids}-type`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.keys(STAGE_TYPE_LABELS).map((value) => (
              <SelectItem key={value} value={value}>
                {tRoot(`labels.types.${value}` as never)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingRow>

      {form.stageType === "swiss" || form.stageType === "individual_swiss" ? (
        <SettingRow htmlFor={`${ids}-rounds`} label={t("swissRounds")}>
          <NumberInput
            id={`${ids}-rounds`}
            integer
            min={1}
            size="sm"
            className="w-24"
            value={form.maxRounds === "" ? null : Number(form.maxRounds)}
            onValueChange={(next) => onChange({ maxRounds: next == null ? "" : String(next) })}
          />
        </SettingRow>
      ) : null}

      {form.stageType === "individual_swiss" ? (
        <>
          <SettingRow htmlFor={`${ids}-pairing`} label={t("pairingMode")} hint={t("pairingModeHelp")}>
            <Select
              value={form.pairingMode}
              onValueChange={(value) => onChange({ pairingMode: value as StagePairingMode })}
            >
              <SelectTrigger id={`${ids}-pairing`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="score">{t("pairingScore")}</SelectItem>
                <SelectItem value="balance">{t("pairingBalance")}</SelectItem>
              </SelectContent>
            </Select>
          </SettingRow>

          <SettingRow htmlFor={`${ids}-playoff`} label={t("playoffTeams")} hint={t("playoffTeamsHelp")}>
            <NumberInput
              id={`${ids}-playoff`}
              integer
              min={1}
              size="sm"
              className="w-24"
              value={form.playoffTeamCount}
              onValueChange={(next) => onChange({ playoffTeamCount: next ?? 4 })}
            />
          </SettingRow>
        </>
      ) : null}

      {form.stageType === "double_elimination" ? (
        <SettingRow htmlFor={`${ids}-grand-final`} label={t("grandFinal")}>
          <Select
            value={form.deGrandFinalType}
            onValueChange={(value) =>
              onChange({ deGrandFinalType: value as "no_reset" | "with_reset" })
            }
          >
            <SelectTrigger id={`${ids}-grand-final`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="no_reset">{t("noReset")}</SelectItem>
              <SelectItem value="with_reset">{t("withReset")}</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>
      ) : null}
      {children}
    </SettingGroup>
  );
}
