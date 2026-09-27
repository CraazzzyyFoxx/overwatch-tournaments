/**
 * Series length as the bracket defines it.
 *
 * The bracket owns how many maps a match plays. The configuration lives in
 * `Stage.best_of`, the generator resolves it per encounter into
 * `Encounter.best_of`, and an admin may override a single encounter from the
 * edit dialog. Every surface that needs to talk about Bo N — the stage editor,
 * the veto config editor, the public map-pool page — reads it from here so the
 * three cannot drift.
 *
 * `resolveBestOf` mirrors the backend's `services/admin/best_of.py`, and
 * `buildSequenceForBestOf` mirrors `services/encounter/veto_session.py`. Keep
 * them in step: the veto room runs the backend's sequence, so a divergence here
 * is a UI that previews steps the captains will not be asked to take.
 */
import { bracketRoundLabelEn, type BracketRoundShape } from "@/lib/bracket/round-name";
import type { StageBestOfConfig, StageType, VetoSequenceToken } from "@/types/tournament.types";

export const DEFAULT_BEST_OF = 3;

/** Series lengths the stage editor offers. Bo4/Bo6 are legal but unused. */
export const BEST_OF_OPTIONS = [1, 2, 3, 5, 7] as const;

/** Opening bans a generated sequence uses when the pool can spare them. */
const LEAD_BANS = 2;

/**
 * Resolve the series length for one round. Precedence matches the backend:
 * `final` (elimination stages, last round) -> `by_round[round]` -> `default`.
 *
 * `isFinal` is the caller's call because the server decides it from the max
 * round of the *generated* encounter set, which the client cannot see. Callers
 * previewing a stage approximate it with `max_rounds` and should present the
 * result as the configured value rather than a promise.
 */
export function resolveBestOf(
  config: StageBestOfConfig,
  round: number,
  { isFinal = false }: { isFinal?: boolean } = {}
): number {
  if (isFinal && config.final != null) return config.final;
  const byRound = config.by_round[String(round)];
  if (byRound != null) return byRound;
  return config.default;
}

/** True when a stage's rounds do not all play the same series length. */
export function hasPerRoundBestOf(config: StageBestOfConfig): boolean {
  return Object.keys(config.by_round).length > 0 || config.final != null;
}

/**
 * The longest series a stage's config can produce, over every round it sets.
 *
 * A pool that has to cover a whole stage must be sized to this, not to the
 * stage's `default`: the server plays the first `best_of` groups of a slot pool
 * and refuses to open the room when there are fewer (`pick_ban_session`
 * `REASON_SLOT_COUNT_MISMATCH`), so the final's Bo5 decides the count.
 */
export function maxBestOf(config: StageBestOfConfig): number {
  return Math.max(config.default, config.final ?? 0, ...Object.values(config.by_round));
}

/** A round the best-of editor can target, identified by its `by_round` key. */
interface BestOfRoundOption {
  /** Signed round number — negative is a lower-bracket round. */
  round: number;
  label: string;
}

/** A group of rounds in the editor; `label === null` renders as a flat list. */
export interface BestOfRoundSection {
  key: string;
  label: string | null;
  rounds: BestOfRoundOption[];
}

export interface StageBestOfShape {
  stageType: StageType;
  /** `Stage.max_rounds`. A fallback used only when the team count is unknown. */
  maxRounds: number;
  /**
   * The team count that fixes this bracket's depth: total teams for single
   * elimination, upper-bracket teams (post-split) for double elimination.
   * `0` when nothing is seeded and no count can be derived, which falls back
   * to `maxRounds`.
   */
  bracketTeamCount?: number;
  /** DE "split" seeding: half the teams start in the lower bracket. */
  splitLowerBracket?: boolean;
  /** Round keys already configured, so an override is never hidden. */
  configuredRounds?: number[];
}

/**
 * The rounds the best-of editor offers, grouped by bracket.
 *
 * Double elimination numbers its rounds by sign — upper bracket 1..U, grand
 * final U+1, lower bracket -1..-L (`services/bracket/double_elimination.py`) —
 * so a single flat `Round 1..max_rounds` list can neither reach a lower-bracket
 * round nor say which bracket a positive round belongs to. Organizers who want
 * "Bo5 in the upper bracket only" reached for `default` instead, which lengthens
 * every match in both brackets.
 *
 * The grand final is NOT offered here: `final` already targets it (and takes
 * precedence over `by_round`), so giving it a second key would let the two
 * disagree with `final` silently winning.
 *
 * The depth is derived from the team count, exact for the power-of-two sizes
 * the generator builds cleanly and possibly over-counting a lower bracket
 * shortened by first-round byes. Over-counting is the safe direction: a key no
 * encounter carries is inert, while a missing row is a round the organizer
 * cannot configure at all. `maxRounds` is only a last-resort fallback for a
 * bracket whose team count is still unknown — it is an independent admin
 * planning field, not the real round count.
 */
export function stageBestOfRoundSections({
  stageType,
  maxRounds,
  bracketTeamCount = 0,
  splitLowerBracket = false,
  configuredRounds = []
}: StageBestOfShape): BestOfRoundSection[] {
  const flatRounds = Math.max(1, Math.floor(maxRounds) || 1);

  if (stageType !== "double_elimination") {
    // A single elimination's round count is `ceil(log2(teams))`
    // (`services/bracket/single_elimination.py`), NOT `max_rounds` — a 5-team
    // and a 32-team bracket carry different depths a shared planning default
    // cannot express. Swiss / round-robin play a flat `1..max_rounds` the
    // caller already knows.
    const depth =
      stageType === "single_elimination" && bracketTeamCount >= 2
        ? Math.ceil(Math.log2(bracketTeamCount))
        : flatRounds;
    const shape: BracketRoundShape = { rounds: countUp(depth), finalRounds: [] };
    return withUnlistedRounds(
      [{ key: "rounds", label: null, rounds: labelRounds(shape.rounds, shape) }],
      configuredRounds,
      shape
    );
  }

  // `maxRounds` counts the grand final, the bracket's rounds do not.
  const upperRounds =
    bracketTeamCount >= 2 ? Math.ceil(Math.log2(bracketTeamCount)) : Math.max(1, flatRounds - 1);

  // Each upper round after the first drops losers into a lower round and the
  // survivors play a reduction round; lower-bracket seeds add an opening round
  // plus the reduction that merges them with the upper bracket's first losers.
  const lowerRounds = Math.max(0, 2 * (upperRounds - 1) + (splitLowerBracket ? 2 : 0));

  // The grand final is `upperRounds + 1` and its reset the round after
  // (`double_elimination.generate`). Neither is an editable row — `final` owns
  // the grand final — but both belong to the shape, so a `by_round` key on one
  // reads by name and the round below them reads "UB Final" rather than as bare
  // numbers. A stage with no reset simply never carries that round.
  const upper = countUp(upperRounds);
  const lower = countUp(lowerRounds).map((depth) => -depth);
  const grandFinal = upperRounds + 1;
  const shape: BracketRoundShape = {
    rounds: [...upper, ...lower, grandFinal, grandFinal + 1],
    finalRounds: [grandFinal, grandFinal + 1]
  };

  const sections: BestOfRoundSection[] = [
    { key: "upper", label: "Upper bracket", rounds: labelRounds(upper, shape) }
  ];
  if (lowerRounds > 0) {
    sections.push({ key: "lower", label: "Lower bracket", rounds: labelRounds(lower, shape) });
  }
  return withUnlistedRounds(sections, configuredRounds, shape);
}

function countUp(count: number): number[] {
  return Array.from({ length: Math.max(0, count) }, (_, index) => index + 1);
}

function labelRounds(rounds: number[], shape: BracketRoundShape): BestOfRoundOption[] {
  return rounds.map((round) => ({ round, label: bracketRoundLabelEn(round, shape) }));
}

/**
 * Append any configured round the sections above do not offer.
 *
 * The offered depth is derived, so a stage whose bracket is a different shape
 * than the derivation assumed (or one configured before this editor grouped its
 * rounds) can carry a `by_round` key with nowhere to render. Such a key still
 * changes matches, so it gets a row rather than becoming an invisible override.
 */
function withUnlistedRounds(
  sections: BestOfRoundSection[],
  configuredRounds: number[],
  shape: BracketRoundShape
): BestOfRoundSection[] {
  const offered = new Set(sections.flatMap((section) => section.rounds.map((row) => row.round)));
  const unlisted = [...new Set(configuredRounds)]
    .filter((round) => !offered.has(round))
    .sort((left, right) => right - left);
  if (unlisted.length === 0) return sections;
  return [
    ...sections,
    {
      key: "other",
      label: "Other configured rounds",
      rounds: labelRounds(unlisted, shape)
    }
  ];
}

/**
 * Generate the veto step sequence that plays exactly `bestOf` maps.
 *
 * A pair of opening bans, then alternating picks, then a decider when the
 * series length is odd. This reproduces the Bo2/Bo3/Bo5 shapes the editor used
 * to hardcode and extends to any N, so a bracket configured Bo7 has a sequence.
 * Bo1 is the exception: its standard veto bans the pool down to one map.
 *
 * Opening bans are dropped as needed to keep the sequence no longer than the
 * pool, which is what the server validates on upsert.
 */
export function buildSequenceForBestOf(bestOf: number, poolSize: number): VetoSequenceToken[] {
  if (poolSize < 1) return [];
  if (bestOf <= 1) {
    const bans: VetoSequenceToken[] = Array.from({ length: poolSize - 1 }, (_, index) =>
      index % 2 === 0 ? "ban_first" : "ban_second"
    );
    return [...bans, "decider"];
  }

  // A pool smaller than the series cannot play the whole series; clamp rather
  // than preview steps the engine would run off the end of.
  const played = Math.min(bestOf, poolSize);
  const pickCount = played % 2 === 1 ? played - 1 : played;
  const banCount = Math.max(0, Math.min(LEAD_BANS, poolSize - played));

  const tokens: VetoSequenceToken[] = Array.from({ length: banCount }, (_, index) =>
    index % 2 === 0 ? "ban_first" : "ban_second"
  );
  for (let index = 0; index < pickCount; index += 1) {
    tokens.push(index % 2 === 0 ? "pick_first" : "pick_second");
  }
  if (played % 2 === 1) tokens.push("decider");
  return tokens;
}
