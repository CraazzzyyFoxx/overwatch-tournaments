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

export function getMatchingScorePreset(homeScore: number, awayScore: number) {
  return GROUP_STAGE_SCORE_PRESETS.find(
    (preset) => preset.homeScore === homeScore && preset.awayScore === awayScore
  );
}

export function isGroupStageScoreContext(stage?: ScoreStageLike, stageItem?: ScoreStageItemLike) {
  return (
    stage?.stage_type === "round_robin" ||
    stage?.stage_type === "swiss" ||
    stageItem?.type === "group"
  );
}
