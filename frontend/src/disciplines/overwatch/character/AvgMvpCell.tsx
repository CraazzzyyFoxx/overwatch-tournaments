"use client";

import { useTranslations } from "next-intl";

import { SummaryCellBox } from "@/components/profile/atoms";
import type { SlotProps } from "@/disciplines/types";
import type { UserTournamentEntry } from "@/types/user.types";

import { resolveMvpPlacement } from "../match/mvp";

/** Mean MVP placement across the user's matches in the entries (`impact_rank`), or null when nothing is recorded. */
export const avgMvpPlacement = (entries: Pick<UserTournamentEntry, "encounters">[]): number | null => {
  let sum = 0;
  let count = 0;
  for (const t of entries) {
    for (const enc of t.encounters) {
      for (const match of enc.matches ?? []) {
        const placement = resolveMvpPlacement(match.viewer?.facts);
        if (placement != null) {
          sum += placement;
          count += 1;
        }
      }
    }
  }
  return count > 0 ? sum / count : null;
};

/** Overwatch's "avg MVP" cell of a tournament dossier's summary strip (the `tournamentSummary` slot). */
const AvgMvpCell = ({ entries }: SlotProps["tournamentSummary"]) => {
  const t = useTranslations();
  const avg = avgMvpPlacement(entries);
  return <SummaryCellBox label={t("users.tournaments.dossier.summary.avgMvp")} value={avg != null ? avg.toFixed(1) : "—"} />;
};

export default AvgMvpCell;
