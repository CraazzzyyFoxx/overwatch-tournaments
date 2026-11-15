"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import type { SeedRanking } from "@/types/tournament.types";

import {
  BRACKET_STAGE_TYPES,
  SEED_RANKING_LABELS,
  SEED_RANKING_LABEL_KEYS
} from "@/lib/bracket/projection";
import type { SectionProps } from "./types";

/** How a bracket stage orders the teams seated from its flow input; a group stage has nothing to seed. */
export function SeedingSection({ form, onChange }: Pick<SectionProps, "form" | "onChange">) {
  const t = useTranslations("adminBracket.settings");
  const tRoot = useTranslations("adminBracket");
  const ids = useId();
  if (!BRACKET_STAGE_TYPES.includes(form.stageType)) return null;

  return (
    <SettingGroup id="stage-seeding" title={tRoot("editor.seeding")} description={t("fillHelp")}>
      <SettingRow htmlFor={`${ids}-seed-ranking`} label={t("bracketSeeds")} hint={t("seedHelp")}>
        <Select
          value={form.seedRanking}
          onValueChange={(value) => onChange({ seedRanking: value as SeedRanking })}
        >
          <SelectTrigger id={`${ids}-seed-ranking`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(SEED_RANKING_LABELS) as SeedRanking[]).map((value) => (
              <SelectItem key={value} value={value}>
                {tRoot(`labels.seedRanking.${SEED_RANKING_LABEL_KEYS[value]}` as never)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingRow>
    </SettingGroup>
  );
}
