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
import type { Tone } from "@/components/kit/tone";
import { resolveBestOf, stageBestOfRoundSections } from "@/lib/tournament/best-of";
import { bracketRoundLabelEn } from "@/lib/bracket/round-name";
import type {
  SeedRanking,
  Stage,
  StageBestOfConfig,
  StageItem,
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

export const STAGE_TYPE_LABELS: Record<StageType, string> = {
  round_robin: "Round Robin",
  single_elimination: "Single Elimination",
  double_elimination: "Double Elimination",
  swiss: "Swiss",
  ffa_league: "FFA League"
};

export const STAGE_ITEM_TYPE_LABELS: Record<StageItemType, string> = {
  group: "Group",
  bracket_upper: "Upper bracket",
  bracket_lower: "Lower bracket",
  single_bracket: "Single bracket"
};

export const SEED_RANKING_LABELS: Record<SeedRanking, string> = {
  slot: "Slot order (manual / standings)",
  avg_sr: "Highest team avg SR first",
  total_sr: "Highest team total SR first",
  random: "Random (stable per stage)"
};

export const DEFAULT_SWISS_TIEBREAKERS = [
  "points",
  "median_buchholz",
  "buchholz",
  "match_wins",
  "score_differential",
  "head_to_head"
];

export const DEFAULT_RR_TIEBREAKERS = [
  "points",
  "head_to_head",
  "median_buchholz",
  "match_wins",
  "score_differential",
  "buchholz"
];

export const DEFAULT_BRACKET_TIEBREAKERS = [
  "points",
  "head_to_head",
  "median_buchholz",
  "score_differential",
  "match_wins",
  "buchholz"
];

/** Mirrors the backend `ffa_default` preset (`RULE_PRESET_DEFAULTS`). */
export const DEFAULT_FFA_TIEBREAKERS = [
  "points",
  "ffa_game_wins",
  "ffa_score",
  "ffa_last_placement"
];

export const RANKING_PRESETS = [
  { value: "default", label: "System default (based on type)" },
  { value: "challonge_swiss", label: "Challonge Swiss (Buchholz first)" },
  { value: "challonge_round_robin", label: "Challonge Round Robin" },
  { value: "bracket_default", label: "Default bracket" }
] as const;

/** The FFA catalogue: the duel presets order metrics a lobby cannot compute. */
export const FFA_RANKING_PRESETS = [
  { value: "default", label: "System default (based on type)" },
  { value: "ffa_default", label: "FFA default (game wins, then score)" }
] as const;

/** The tiebreak order a stage type falls back to with no preset chosen. */
export function defaultTiebreakOrder(stageType: StageType): string[] {
  if (stageType === "ffa_league") return DEFAULT_FFA_TIEBREAKERS;
  if (stageType === "swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (stageType === "round_robin") return DEFAULT_RR_TIEBREAKERS;
  return DEFAULT_BRACKET_TIEBREAKERS;
}

/** The order a preset dictates; an unknown preset keeps the type default. */
export function tiebreakOrderForPreset(preset: string, stageType: StageType): string[] {
  if (preset === "challonge_swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (preset === "challonge_round_robin") return DEFAULT_RR_TIEBREAKERS;
  if (preset === "bracket_default") return DEFAULT_BRACKET_TIEBREAKERS;
  if (preset === "ffa_default") return DEFAULT_FFA_TIEBREAKERS;
  return defaultTiebreakOrder(stageType);
}

export function getStageTeamSlots(stage: Stage) {
  return stage.items.reduce((acc, item) => acc + item.inputs.length, 0);
}

export function getStageAssignedTeams(stage: Stage) {
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

export function getTeamName(teamById: Map<number, Team>, teamId: number | null) {
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
  if (stage.is_completed) return "Completed";
  if (stage.is_active) return "Active";
  // Bracket generated ahead of activation: visible to organizers, not yet
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

export function getInputDisplayLabel(
  input: StageItemInput,
  stages: Stage[],
  teamById: Map<number, Team>
) {
  if (input.team_id != null) return getTeamName(teamById, input.team_id);

  if (
    input.input_type === "tentative" &&
    input.source_stage_item_id != null &&
    input.source_position != null
  ) {
    const sourceItem = stages
      .flatMap((stage) => stage.items)
      .find((item) => item.id === input.source_stage_item_id);
    const groupName = sourceItem?.name ?? `Item ${input.source_stage_item_id}`;
    return `Winner of ${groupName} #${input.source_position}`;
  }

  return "Empty slot";
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
export type BracketTeamCountSource = "seeded" | "slots" | "projected" | "unknown";

/**
 * The upper/lower seed counts the preceding group stage feeds into `stage`,
 * mirroring `_preceding_group_stage` + `_projected_bracket_seed_counts`: the
 * one Swiss/round-robin stage of the latest EARLIER phase sends on each group's
 * OWN `advance_count`, falling back to the stage's number where a group sets
 * none, and a split double elimination splits EACH group's share (the odd team
 * out goes up) rather than halving the total — which for an odd `advance_count`
 * is a differently shaped bracket.
 *
 * Stages sharing `order` run in parallel, so a same-phase group stage is a
 * sibling, not a source; several of them in the earlier phase is ambiguous and
 * projects nothing, exactly as the server refuses to wire one.
 */
export function projectedBracketSeedCounts(
  stage: Stage,
  splitLowerBracket: boolean,
  stages: Stage[]
): { upper: number; lower: number } {
  const earlier = stages
    .filter(
      (candidate) =>
        candidate.order < stage.order &&
        (candidate.stage_type === "swiss" || candidate.stage_type === "round_robin")
    )
    .sort((left, right) => right.order - left.order || right.id - left.id);
  const phase = earlier.at(0)?.order;
  const sources = earlier.filter((candidate) => candidate.order === phase);
  const source = sources.length === 1 ? sources[0] : undefined;
  if (!source) return { upper: 0, lower: 0 };

  const isSplitDe = stage.stage_type === "double_elimination" && splitLowerBracket;
  const hasLowerItem = isSplitDe && stage.items.some((item) => item.type === "bracket_lower");
  const split = (advance: number) =>
    hasLowerItem
      ? { upper: advance - Math.floor(advance / 2), lower: Math.floor(advance / 2) }
      : { upper: advance, lower: 0 };

  const stageDefault = split(source.advance_count ?? 0);
  // A source stage with no items still behaves as one implicit group.
  const groups: (StageItem | null)[] = source.items.length > 0 ? source.items : [null];
  let upper = 0;
  let lower = 0;
  for (const group of groups) {
    const share = group?.advance_count ? split(group.advance_count) : stageDefault;
    upper += share.upper;
    lower += share.lower;
  }

  if (upper + lower === 0) return { upper: 0, lower: 0 };
  if (lower > 0) return { upper, lower };
  if (isSplitDe) {
    // One bracket item holds both halves; the seed list is split down the middle.
    return { upper: Math.floor(upper / 2), lower: upper - Math.floor(upper / 2) };
  }
  return { upper, lower: 0 };
}

/**
 * The team count that fixes a bracket's depth, mirroring `generate_encounters`
 * (services/admin/stage.py): total teams for single elimination or a non-split
 * double elimination; the upper-bracket half for a split double elimination
 * (a dedicated Lower bracket item, or the first half of a single bracket item's
 * seeds).
 *
 * Seeded inputs — then empty slots — are ground truth when present. Before
 * either exists (the common case: a playoff wired only after its groups finish)
 * the count is projected from what the preceding group stage's groups advance,
 * so the best-of editor offers the bracket that WILL be generated rather than a
 * `max_rounds` guess that has no relation to the team count.
 */
export function resolveBracketTeamCount(
  stage: Stage,
  splitLowerBracket: boolean,
  stages: Stage[]
): { count: number; source: BracketTeamCountSource } {
  const countInputs = (items: StageItem[]) => {
    const assigned = items.reduce(
      (acc, item) => acc + item.inputs.filter((input) => input.team_id != null).length,
      0
    );
    if (assigned > 0) return { count: assigned, source: "seeded" as const };
    return { count: items.reduce((acc, item) => acc + item.inputs.length, 0), source: "slots" as const };
  };

  const isSplitDe = stage.stage_type === "double_elimination" && splitLowerBracket;
  const hasLowerItem = stage.items.some((item) => item.type === "bracket_lower");

  if (!isSplitDe) {
    const own = countInputs(stage.items);
    if (own.count > 0) return own;
  } else if (hasLowerItem) {
    const own = countInputs(stage.items.filter((item) => item.type !== "bracket_lower"));
    if (own.count > 0) return own;
  } else {
    const own = countInputs(stage.items);
    if (own.count > 0) return { count: Math.floor(own.count / 2), source: own.source };
  }

  // Nothing wired yet: project from the group stage that will seed this one.
  const projected = projectedBracketSeedCounts(stage, splitLowerBracket, stages).upper;
  return { count: projected, source: projected > 0 ? "projected" : "unknown" };
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

export interface ProjectedRound {
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
  seeds: { upper: number; lower: number };
  advanceCount: number | null;
  /** Every group's own resolved count, in item order — `[3, 5]` reads "top 3 / 5". */
  advanceCounts: number[];
  /** Sum of `advanceCounts`: what this stage sends onward. */
  advancingTotal: number;
  rounds: ProjectedRound[];
}

/**
 * The read-only shape of the stage as it would be generated right now.
 *
 * `stageType`, `splitLowerBracket`, `maxRounds` and `bestOf` are taken as
 * arguments rather than read off `stage`, so the preview follows the editor's
 * unsaved draft instead of lagging one save behind it.
 */
export function projectStage({
  stage,
  stages,
  stageType,
  splitLowerBracket,
  maxRounds,
  bestOf
}: {
  stage: Stage;
  stages: Stage[];
  stageType: StageType;
  splitLowerBracket: boolean;
  maxRounds: number;
  bestOf: StageBestOfConfig;
}): StageProjection {
  const isBracket = BRACKET_STAGE_TYPES.includes(stageType);
  const isGroups = GROUP_STAGE_TYPES.includes(stageType);
  const isFfa = FFA_STAGE_TYPES.includes(stageType);
  const slots = getStageTeamSlots(stage);
  const assigned = getStageAssignedTeams(stage);
  const bracketTeams = resolveBracketTeamCount(stage, splitLowerBracket, stages);
  // A stage with no items still counts as one implicit group on the default.
  // An FFA lobby advances a top N the same way a group does.
  const advanceCounts =
    isGroups || isFfa
      ? (stage.items.length > 0 ? stage.items : [null]).map(
          (item) => item?.advance_count ?? stage.advance_count ?? 0
        )
      : [];
  const advancingTotal = advanceCounts.reduce((acc, count) => acc + count, 0);

  const sections = stageBestOfRoundSections({
    stageType,
    maxRounds,
    bracketTeamCount: bracketTeams.count,
    splitLowerBracket,
    configuredRounds: Object.keys(bestOf.by_round ?? {}).map(Number)
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
      label: bracketRoundLabelEn(grandFinalRound, {
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
    seeds: projectedBracketSeedCounts(stage, splitLowerBracket, stages),
    advanceCount: stage.advance_count ?? null,
    advanceCounts,
    advancingTotal,
    rounds
  };
}
