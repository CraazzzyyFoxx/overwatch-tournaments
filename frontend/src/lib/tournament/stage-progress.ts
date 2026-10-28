import type { useTranslations } from "next-intl";

import { pickCurrentStage } from "@/lib/tournament/stages";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

/**
 * The root translator `stageProgress` (and the tournament facts beside it)
 * take: next-intl's `useTranslations()` / `await getTranslations()` result,
 * which next-intl does not name, so callers can hand their `t` straight
 * through (strictFunctionTypes-safe).
 */
export type Translate = ReturnType<typeof useTranslations<never>>;

export interface StageProgress {
  label: string;
  pct: number;
  /** The bar's `Tone` (`components/ui/tone.ts`), handed to `Progress` as is. */
  tone: "accent" | "warning" | "neutral";
}

// Apart from `stages.ts` on purpose: the admin zone imports that module's
// stage-ordering helpers, and the `tournamentsList` labels below would put the
// whole namespace in the admin message bundle (lint:zones Z4).
//
// Coarse stage-progress proxy from stage completion flags. Real "X/Y matches"
// requires a precomputed backend field (see plan C2); until then we render a
// graceful label + bar derived from stages.is_completed and the current stage.
//
// Bucketed by the status's presentation variant rather than by listing statuses
// again: which statuses read as "signing up" is already decided once, in
// `@/lib/tournament/status`.
export function stageProgress(
  tournament: Tournament,
  status: TournamentStatus,
  t: Translate
): StageProgress {
  switch (getTournamentStatusMeta(status).variant) {
    case "finished":
      return { label: t("tournamentsList.stage.final"), pct: 100, tone: "accent" };
    case "upcoming":
      return { label: t("tournamentsList.stage.signups"), pct: 30, tone: "warning" };
    case "draft":
      return { label: t("tournamentsList.stage.setup"), pct: 20, tone: "neutral" };
  }

  const stages = tournament.stages ?? [];
  const total = stages.length;
  const completed = stages.filter((stage) => stage.is_completed).length;
  const current = pickCurrentStage(stages, status);
  const pct = total > 0 ? Math.min(95, Math.max(10, Math.round((completed / total) * 100))) : 50;
  return { label: current?.name ?? t("common.live"), pct, tone: "accent" };
}
