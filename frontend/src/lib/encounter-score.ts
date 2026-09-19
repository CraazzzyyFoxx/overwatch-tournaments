import type { StageItemType, StageType } from "@/types/tournament.types";

export type EncounterScore = {
  homeScore: number;
  awayScore: number;
};

export type EncounterScorePreset = EncounterScore & {
  label: string;
  description: string;
};

type ScoreStageLike = {
  stage_type?: StageType | string | null;
} | null | undefined;

type ScoreStageItemLike = {
  type?: StageItemType | string | null;
} | null | undefined;

export const GROUP_STAGE_SCORE_PRESETS: EncounterScorePreset[] = [
  { label: "2-0", description: "Home sweep", homeScore: 2, awayScore: 0 },
  { label: "2-1", description: "Home close win", homeScore: 2, awayScore: 1 },
  { label: "1-1", description: "Draw", homeScore: 1, awayScore: 1 },
  { label: "1-2", description: "Away close win", homeScore: 1, awayScore: 2 },
  { label: "0-2", description: "Away sweep", homeScore: 0, awayScore: 2 },
];

export function clampScoreValue(value: string | number): number {
  const parsed = typeof value === "number" ? value : Number.parseInt(value, 10);

  if (!Number.isFinite(parsed)) {
    return 0;
  }

  return Math.max(0, Math.floor(parsed));
}

export function isGroupStageScoreContext(stage?: ScoreStageLike, stageItem?: ScoreStageItemLike) {
  return (
    stage?.stage_type === "round_robin" ||
    stage?.stage_type === "swiss" ||
    stageItem?.type === "group"
  );
}

/** Human-readable description key (reused i18n keys under matchEdit.presetDescriptions). */
function describeScore(homeScore: number, awayScore: number): string {
  if (homeScore === awayScore) return "Draw";
  if (homeScore > awayScore) return awayScore === 0 ? "Home sweep" : "Home close win";
  return homeScore === 0 ? "Away sweep" : "Away close win";
}

/**
 * All valid final scores for a best-of-N series. Winner needs
 * `floor(N/2)+1` maps; the loser can take up to `N - w` (early clinch). Even
 * series (e.g. BO2) additionally allow a drawn `N/2 - N/2`.
 */
export function validSeriesScores(bestOf: number): EncounterScorePreset[] {
  if (!Number.isInteger(bestOf) || bestOf < 1) return [];
  const win = Math.floor(bestOf / 2) + 1;
  const maxLoser = bestOf - win;
  const scores: EncounterScore[] = [];
  for (let loser = 0; loser <= maxLoser; loser++) {
    scores.push({ homeScore: win, awayScore: loser });
  }
  if (bestOf % 2 === 0) {
    scores.push({ homeScore: bestOf / 2, awayScore: bestOf / 2 });
  }
  for (let loser = maxLoser; loser >= 0; loser--) {
    scores.push({ homeScore: loser, awayScore: win });
  }
  return scores.map((score) => ({
    ...score,
    label: `${score.homeScore}-${score.awayScore}`,
    description: describeScore(score.homeScore, score.awayScore)
  }));
}

/**
 * Quick-result presets for a given series length. Short series (BO1-BO3) show
 * their discrete valid outcomes; longer series (BO5+) return none — the form
 * falls back to manual entry only.
 */
export function getScorePresetsForBestOf(bestOf: number): EncounterScorePreset[] {
  if (!Number.isInteger(bestOf) || bestOf < 1 || bestOf > 3) return [];
  return validSeriesScores(bestOf);
}
