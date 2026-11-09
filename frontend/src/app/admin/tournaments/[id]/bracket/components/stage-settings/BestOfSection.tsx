"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { BEST_OF_OPTIONS } from "@/lib/tournament/best-of";

import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import type { SectionProps } from "./types";

/**
 * One series length for every match of a non-elimination stage. An elimination bracket is configured on its own
 * round headers (the Bracket tab) instead, and a single match is overridden from its edit dialog.
 */
export function BestOfSection({
  form,
  onChange,
  onApplyToExisting,
  applying
}: Omit<SectionProps, "stage"> & {
  /** Writes the SAVED best-of onto matches that already exist, right away. */
  onApplyToExisting: () => void;
  applying: boolean;
}) {
  const t = useTranslations("adminBracket.settings");
  const tRoot = useTranslations("adminBracket");
  const ids = useId();
  // An FFA lobby plays games, not a series: `best_of` is how many games it
  // plans (`FfaEncounterService.create_lobby`). "Bo5" would read it as a duel.
  const isFfa = FFA_STAGE_TYPES.includes(form.stageType);

  return (
    <SettingGroup id="stage-best-of" title={isFfa ? t("lobbyLength") : tRoot("editor.bestOf")}>
      <SettingRow htmlFor={`${ids}-default`} label={isFfa ? t("gamesPerLobby") : t("allMatches")}>
        <Select
          value={String(form.bestOf.default)}
          onValueChange={(value) => onChange({ bestOf: { ...form.bestOf, default: Number(value) } })}
        >
          <SelectTrigger id={`${ids}-default`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {BEST_OF_OPTIONS.map((n) => (
              <SelectItem key={n} value={String(n)}>
                {isFfa ? t("games", { count: n }) : `Bo${n}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingRow>

      {/* One expression, not JSX text: Next's SWC transform drops the leading
          space of a multi-line text node that follows an expression and carries
          an HTML entity, which read as "Baked into lobbieson (re)generation". */}
      <SettingRow
        label={t("existingMatches")}
        hint={t("baked", { target: isFfa ? t("lobbies") : t("matches") })}
      >
        <Button type="button" size="sm" variant="outline" disabled={applying} onClick={onApplyToExisting}>
          {applying ? <Spinner /> : null}
          {t("applyExisting")}
        </Button>
      </SettingRow>
    </SettingGroup>
  );
}
