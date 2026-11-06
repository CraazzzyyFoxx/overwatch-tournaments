/**
 * Stage vocabulary and the bracket-projection maths of the Bracket tab (T4).
 *
 * Everything here is pure: it was co-located with 2450 lines of `StageManager`
 * JSX, which is why the projection — the part that mirrors the backend
 * generator and is the easiest thing in the tab to get wrong — had never been
 * tested. `projection.test.ts` pins it.
 *
 * The round shapes come from `@/lib/tournament/best-of`, which is already mirrored from
 * `services/bracket/*`; nothing new is derived here, so the preview and the
 * best-of editor cannot disagree.
 */
import type { Tone } from "@/components/ui/tone";
import { resolveBestOf, stageBestOfRoundSections } from "@/lib/tournament/best-of";
import { bracketRoundLabelEn, type BracketRoundShape } from "@/lib/bracket/round-name";
import type {
  SeedRanking,
  Stage,
  StageBestOfConfig,
  StageItemInput,
  StageItemType,
  StageType
} from "@/types/tournament.types";
import type { Team } from "@/types/team.types";

/**
 * One row of `adminService.getStagesProgress`, derived from the service so the
 * list and the editor cannot drift from the payload shape.
 */
export type StageProgress = Awaited<
  ReturnType<typeof import("@/services/admin.service").default.getStagesProgress>
>[number];

export const BRACKET_STAGE_TYPES: StageType[] = ["single_elimination", "double_elimination"];
export const GROUP_STAGE_TYPES: StageType[] = ["round_robin", "swiss"];
/**
 * FFA is its own family, in NEITHER list above: its encounters are lobbies of
 * many teams, so nothing that pairs opponents (seeding, merging, Buchholz,
 * round-robin round counts) applies — but its items are still groups that
 * advance a top N, which is why `getDefaultStageItemType` answers "group".
 */
export const FFA_STAGE_TYPES: StageType[] = ["ffa_league"];
/**
 * Individual Swiss rounds reshuffle players into new rosterless teams, so —
 * like FFA — it is in neither family above and draws one panel per stage.
 */
export const INDIVIDUAL_SWISS_STAGE_TYPES: StageType[] = ["individual_swiss"];

export const STAGE_TYPE_LABELS: Record<StageType, string> = {
  round_robin: "Round Robin",
  single_elimination: "Single Elimination",
  double_elimination: "Double Elimination",
  swiss: "Swiss",
  ffa_league: "FFA",
  individual_swiss: "Individual Swiss"
};

export const STAGE_ITEM_TYPE_LABELS: Record<StageItemType, string> = {
  group: "Group",
  bracket_upper: "Upper bracket",
  bracket_lower: "Lower bracket",
  single_bracket: "Single bracket"
};

export const SEED_RANKING_LABELS: Record<SeedRanking, string> = {
  slot: "Slot order (manual / standings)",
  source: "Input order",
  avg_sr: "Highest team avg SR first",
  total_sr: "Highest team total SR first",
  random: "Random (stable per stage)",
  cross: "Cross groups (A1–B2)",
  snake: "Snake groups (A1, B1, A2, B2)"
};
export const SEED_RANKING_LABEL_KEYS: Record<SeedRanking, string> = {
  slot: "slot",
  source: "source",
  avg_sr: "avg_sr",
  total_sr: "total_sr",
  random: "random",
  cross: "cross",
  snake: "snake"
};

const DEFAULT_SWISS_TIEBREAKERS = [
  "points",
  "median_buchholz",
  "buchholz",
  "match_wins",
  "score_differential",
  "head_to_head"
];

const DEFAULT_RR_TIEBREAKERS = [
  "points",
  "head_to_head",
  "median_buchholz",
  "match_wins",
  "score_differential",
  "buchholz"
];

const DEFAULT_BRACKET_TIEBREAKERS = [
  "points",
  "head_to_head",
  "median_buchholz",
  "score_differential",
  "match_wins",
  "buchholz"
];

/**
 * Mirrors the backend `ffa_default` preset (`RULE_PRESET_DEFAULTS`).
 *
 * Not a constant any more: the third step is the sum of the stage's FIRST
 * column, and a stage that records nothing per game simply has no such step.
 */
function ffaDefaultTiebreakers(columns: readonly { key: string }[] = []): string[] {
  const first = columns[0]?.key;
  return first
    ? ["points", "ffa_game_wins", `ffa_stat:${first}`, "ffa_last_placement"]
    : ["points", "ffa_game_wins", "ffa_last_placement"];
}

export const RANKING_PRESETS = [
  { value: "default", label: "System default (based on type)", labelKey: "default" },
  { value: "challonge_swiss", label: "Challonge Swiss (Buchholz first)", labelKey: "challonge_swiss" },
  { value: "challonge_round_robin", label: "Challonge Round Robin", labelKey: "challonge_round_robin" },
  { value: "bracket_default", label: "Default bracket", labelKey: "bracket_default" }
] as const;

/** The FFA catalogue: the duel presets order metrics a lobby cannot compute. */
export const FFA_RANKING_PRESETS = [
  { value: "default", label: "System default (based on type)", labelKey: "default" },
  { value: "ffa_default", label: "FFA default (game wins, then score)", labelKey: "ffa_default" }
] as const;

/** The tiebreak order a stage type falls back to with no preset chosen. */
export function defaultTiebreakOrder(
  stageType: StageType,
  ffaColumns: readonly { key: string }[] = []
): string[] {
  if (stageType === "ffa_league") return ffaDefaultTiebreakers(ffaColumns);
  if (stageType === "swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (stageType === "round_robin") return DEFAULT_RR_TIEBREAKERS;
  return DEFAULT_BRACKET_TIEBREAKERS;
}

/** The order a preset dictates; an unknown preset keeps the type default. */
export function tiebreakOrderForPreset(
  preset: string,
  stageType: StageType,
  ffaColumns: readonly { key: string }[] = []
): string[] {
  if (preset === "challonge_swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (preset === "challonge_round_robin") return DEFAULT_RR_TIEBREAKERS;
  if (preset === "bracket_default") return DEFAULT_BRACKET_TIEBREAKERS;
  if (preset === "ffa_default") return ffaDefaultTiebreakers(ffaColumns);
  return defaultTiebreakOrder(stageType, ffaColumns);
}

function getStageTeamSlots(stage: Stage) {
  return stage.items.reduce((acc, item) => acc + item.inputs.length, 0);
}

function getStageAssignedTeams(stage: Stage) {
  return stage.items.reduce(
    (acc, item) => acc + item.inputs.filter((input) => input.team_id != null).length,
    0
  );
}

export function getAssignedTeamIds(stage: Stage) {
  return new Set(
    stage.items.flatMap((item) =>
      item.inputs.map((input) => input.team_id).filter((teamId): teamId is number => teamId != null)
    )
  );
}

export function getDefaultStageItemType(stageType: StageType): StageItemType {
  return BRACKET_STAGE_TYPES.includes(stageType) ? "single_bracket" : "group";
}

function getTeamName(teamById: Map<number, Team>, teamId: number | null) {
  if (teamId == null) return "Empty slot";
  return teamById.get(teamId)?.name ?? `Team #${teamId}`;
}

export function normalizeMaxRounds(value: string | number, fallback = 5) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(1, Math.floor(parsed));
}

export function getProgressPercent(completed: number, total: number) {
  if (total <= 0) return 0;
  return Math.round((completed / total) * 100);
}

export type StageStatus = "Completed" | "Active" | "Preview" | "Draft";

export function getStageStatus(stage: Stage, hasEncounters: boolean): StageStatus {
  if (stage.status === "completed") return "Completed";
  if (stage.status === "live") return "Active";
  // Bracket generated ahead of the start: visible to organizers, not yet
  // usable by captains (`shared.services.bracket.usability.is_encounter_live`).
  if (!stage.is_published && hasEncounters) return "Preview";
  return "Draft";
}

export function getStageStatusTone(stage: Stage, hasEncounters: boolean): Tone {
  const status = getStageStatus(stage, hasEncounters);
  if (status === "Completed") return "success";
  if (status === "Active") return "accent";
  if (status === "Preview") return "info";
  return "neutral";
}

export type InputDisplayLabelInfo = { label: string; key: "team" } | { label: "Empty slot"; key: "emptySlot" };

export function getInputDisplayLabelInfo(
  input: StageItemInput,
  teamById: Map<number, Team>
): InputDisplayLabelInfo {
  if (input.team_id != null) return { label: getTeamName(teamById, input.team_id), key: "team" };
  return { label: "Empty slot", key: "emptySlot" };
}

export function isMergeableGroupStage(stage: Stage) {
  return (
    GROUP_STAGE_TYPES.includes(stage.stage_type) &&
    stage.items.length > 0 &&
    stage.items.every((item) => item.type === "group")
  );
}

export function getDefaultMergedStageName(stage: Stage) {
  const stageName = stage.name.trim();
  const itemNames = new Set(stage.items.map((item) => item.name.trim().toLowerCase()));
  if (!stageName || itemNames.has(stageName.toLowerCase()) || /^[a-z]$/i.test(stageName)) {
    return "Groups";
  }
  return stageName;
}

/**
 * Where a bracket's team count came from, so the preview can say whether it is
 * reading reality or a projection.
 */
export type BracketTeamCountSource = "seeded" | "slots" | "unknown";

/**
 * The team count that fixes a bracket's depth, mirroring `generate_encounters`
 * (services/admin/stage.py): every seed except the ones wired straight into the
 * lower bracket, which is its own `bracket_lower` item and never deepens the
 * upper bracket.
 *
 * Seeded inputs — then empty slots — are ground truth when present. Before
 * either exists (a playoff seated only when it turns `ready`) the count is
 * `unknown` and callers fall back to `max_rounds`.
 */
export function resolveBracketTeamCount(stage: Stage): { count: number; source: BracketTeamCountSource } {
  const upperItems = stage.items.filter((item) => item.type !== "bracket_lower");
  const assigned = upperItems.reduce(
    (acc, item) => acc + item.inputs.filter((input) => input.team_id != null).length,
    0
  );
  if (assigned > 0) return { count: assigned, source: "seeded" };
  const slots = upperItems.reduce((acc, item) => acc + item.inputs.length, 0);
  if (slots > 0) return { count: slots, source: "slots" };

  // Nothing seated yet: the count is unknown until the stage's flow input has results.
  return { count: 0, source: "unknown" };
}

/**
 * The rounds a round robin will play, mirroring `services/bracket/round_robin.py`:
 * the circle method pairs an even field, so `n` teams (padded with a BYE when
 * odd) play `n - 1` rounds. Groups each run their own round robin, so the stage
 * is as long as its largest group.
 *
 * `0` when nothing is wired into the stage yet and the length cannot be derived
 * — a round robin's length follows its team count, NOT `Stage.max_rounds`,
 * which is an independent admin planning field. Callers decide whether to fall
 * back to it.
 */
export function projectedRoundRobinRounds(stage: Stage): number {
  const groupSizes = (stage.items.length > 0 ? stage.items : []).map((item) => {
    const assigned = item.inputs.filter((input) => input.team_id != null).length;
    return assigned > 0 ? assigned : item.inputs.length;
  });
  const largest = groupSizes.length > 0 ? Math.max(...groupSizes) : 0;
  if (largest < 2) return 0;
  return (largest % 2 === 0 ? largest : largest + 1) - 1;
}

interface ProjectedRound {
  /** Signed round number; negative is a lower-bracket round. */
  round: number;
  label: string;
  /** Bracket the round belongs to, `null` for a flat list. */
  section: string | null;
  bestOf: number;
  isFinal: boolean;
}

export interface StageProjection {
  isBracket: boolean;
  isGroups: boolean;
  /** Lobby stage: group-shaped for advancement, but nothing is paired. */
  isFfa: boolean;
  itemCount: number;
  slots: number;
  assigned: number;
  /** Slots with no team yet: the wireframe's "3 unresolved slots". */
  unresolved: number;
  bracketTeams: { count: number; source: BracketTeamCountSource };
  /** Teams seated in the lower bracket. */
  lowerBracketTeamCount: number;
  rounds: ProjectedRound[];
}

/**
 * The read-only shape of the stage as it would be generated right now.
 *
 * `stageType`, `maxRounds` and `bestOf` are taken as arguments rather than read
 * off `stage`, so the preview follows the editor's unsaved draft instead of
 * lagging one save behind it.
 */
export function projectStage({
  stage,
  stageType,
  maxRounds,
  bestOf,
  plannedRounds,
  formatRound = bracketRoundLabelEn
}: {
  stage: Stage;
  stageType: StageType;
  maxRounds: number;
  bestOf: StageBestOfConfig;
  /** The engine's own rounds, when `planned-rounds` has answered. */
  plannedRounds?: readonly number[];
  formatRound?: (round: number, shape: BracketRoundShape) => string;
}): StageProjection {
  const isBracket = BRACKET_STAGE_TYPES.includes(stageType);
  const isGroups = GROUP_STAGE_TYPES.includes(stageType);
  const isFfa = FFA_STAGE_TYPES.includes(stageType);
  const slots = getStageTeamSlots(stage);
  const assigned = getStageAssignedTeams(stage);
  const bracketTeams = resolveBracketTeamCount(stage);
  const lowerBracketTeamCount = stage.items
    .filter((item) => item.type === "bracket_lower")
    .reduce((acc, item) => acc + item.inputs.length, 0);

  const sections = stageBestOfRoundSections({
    stageType,
    maxRounds,
    bracketTeamCount: bracketTeams.count,
    lowerBracketTeamCount,
    configuredRounds: Object.keys(bestOf.by_round ?? {}).map(Number),
    plannedRounds,
    formatRound
  });

  const upper = sections.find((section) => section.key === "upper");
  const grandFinalRound =
    stageType === "double_elimination" && upper && upper.rounds.length > 0
      ? upper.rounds[upper.rounds.length - 1].round + 1
      : null;

  const rounds: ProjectedRound[] = [];
  for (const section of sections) {
    const lastRound = section.rounds[section.rounds.length - 1]?.round;
    for (const option of section.rounds) {
      // `final` outranks `by_round` only on an elimination stage's last round,
      // and in double elimination that is the grand final, added below — never
      // the last upper-bracket round.
      const isFinal =
        stageType === "single_elimination" &&
        section.key === "rounds" &&
        option.round === lastRound;
      rounds.push({
        round: option.round,
        label: option.label,
        section: section.label,
        bestOf: resolveBestOf(bestOf, option.round, { isFinal }),
        isFinal
      });
    }
  }
  if (grandFinalRound != null) {
    rounds.push({
      round: grandFinalRound,
      label: formatRound(grandFinalRound, {
        rounds: [grandFinalRound],
        finalRounds: [grandFinalRound]
      }),
      section: null,
      bestOf: resolveBestOf(bestOf, grandFinalRound, { isFinal: true }),
      isFinal: true
    });
  }

  return {
    isBracket,
    isGroups,
    isFfa,
    itemCount: stage.items.length,
    slots,
    assigned,
    unresolved: Math.max(0, slots - assigned),
    bracketTeams,
    lowerBracketTeamCount,
    rounds
  };
}
