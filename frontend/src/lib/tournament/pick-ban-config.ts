/**
 * Form model of one `PickBanConfig`, and the pure logic the editor needs.
 *
 * The wire shape is deliberately not the form shape. Three of its fields are
 * traps an organizer cannot be expected to reason about, and each is resolved
 * here instead of being handed over raw:
 *
 *   1. `preset` decides whether `sequence` is used at all. The engine rebuilds
 *      the step order from the match's `best_of` unless `preset === "custom"`
 *      (`pick_ban_session.ensure_pick_ban_session`), so a hand-authored
 *      sequence saved with any other preset is silently discarded. The form
 *      therefore exposes the choice as `orderMode` and derives `preset` from
 *      it — never the other way round.
 *   2. `sequence` must be non-empty and internally valid even in bracket order:
 *      `validate_pick_ban_config` runs regardless of preset. Bracket order
 *      stores a generated placeholder for the scope's series length, the same
 *      way the legacy veto editor does.
 *   3. `unique_attribute_per_side_per_round` only ever means `"role"`, and only
 *      for hero configs (`pick_ban_action._attribute_lookup` never resolves it
 *      for `kind=map`). The form models it as a boolean on hero configs alone.
 *
 * `first_pick_rule` is omitted entirely: its type has exactly one member, and
 * the server defaults to it, so a control would be a dead choice.
 *
 * `inheritedFrom` runs the other way: form-only, never sent. It records which
 * saved config a new draft's values were prefilled from (`rescopePickBanDraft`),
 * so the editor can say where they came from instead of presenting a copy of the
 * tournament's rules as if the organizer had typed it.
 */
import {
  DEFAULT_BEST_OF,
  buildSequenceForBestOf,
  hasPerRoundBestOf,
  maxBestOf,
  resolveBestOf,
} from "@/lib/tournament/best-of";
import { projectStage } from "@/lib/bracket/projection";
import type {
  MapVetoMode,
  PickBanConfig,
  PickBanConfigUpsertInput,
  PickBanFirstBanRotation,
  PickBanKind,
  PickBanNoRepeatScope,
  PickBanSequenceToken,
  Stage,
} from "@/types/tournament.types";

/** Candidates a slot needs to ban down to a survivor. Mirrors `pick_ban_session.SLOT_CANDIDATE_FLOOR`. */
const SLOT_CANDIDATE_FLOOR = 2;

/** The only `unique_attribute_per_side_per_round` value the engine implements. */
const ROLE_ATTRIBUTE = "role";

/** The `preset` value that opts a config out of bracket-driven step order. */
const CUSTOM_PRESET = "custom";
/** The `preset` value that opts a config into it. Any non-`custom` value would do. */
const BRACKET_PRESET = "bracket";

/** Where a config's step order comes from. */
export type PickBanOrderMode = "bracket" | "custom";

export type PickBanStepAction = "ban" | "pick" | "protect";
export type PickBanStepSide = "first" | "second";

export const PICK_BAN_STEP_ACTIONS: PickBanStepAction[] = ["ban", "pick", "protect"];
export const PICK_BAN_STEP_SIDES: PickBanStepSide[] = ["first", "second"];

export const PICK_BAN_MODES: MapVetoMode[] = ["pool", "slots"];
export const PICK_BAN_ROTATIONS: PickBanFirstBanRotation[] = [
  "fixed",
  "alternate",
  "result_winner_first",
  "result_loser_first",
  "result_loser_choice",
];
export const PICK_BAN_NO_REPEAT_SCOPES: PickBanNoRepeatScope[] = [
  "none",
  "encounter",
  "encounter_same_side",
];

/** One slot as the editor holds it: no `position`, because list order is it. */
export interface PickBanDraftSlot {
  candidates: number[];
  reserveItemId: number | null;
}

/**
 * One bracket round's groups, as a stage-wide editor holds them.
 *
 * A stored config has no round dimension — the scope key is `(stage, round)`,
 * so per-round groups are N configs, not one. This is the shape the stage
 * screen authors them in before it fans them back out on save.
 */
export interface PickBanDraftRoundSlots {
  round: number;
  slots: PickBanDraftSlot[];
}

/** Scope of the config a draft's values were prefilled from. */
interface PickBanInheritedScope {
  stageId: number | null;
  round: number | null;
}

/**
 * Every field one config's editor owns, typed. Ids are numbers rather than the
 * comma-separated strings the previous editor parsed on save, so an unparseable
 * value cannot exist in the first place.
 */
export interface PickBanDraft {
  /** Null for a config that does not exist yet. */
  configId: number | null;
  kind: PickBanKind;
  stageId: number | null;
  round: number | null;
  mode: MapVetoMode;
  orderMode: PickBanOrderMode;
  firstBanRotation: PickBanFirstBanRotation;
  noRepeatScope: PickBanNoRepeatScope;
  turnTimerSeconds: number | null;
  allowProtect: boolean;
  /** Hero configs only; a map config always sends null. */
  uniqueRolePerRound: boolean;
  /** Only read when `orderMode === "custom"` and `mode === "pool"`. */
  sequence: PickBanSequenceToken[];
  /** Pool mode only. */
  itemIds: number[];
  /** Slots mode, one round's scope. */
  slots: PickBanDraftSlot[];
  /**
   * Slots mode on a stage scope: each round of the stage with its own groups.
   * Empty everywhere else, including a round scope, where `slots` is the round.
   */
  roundSlots: PickBanDraftRoundSlots[];
  /**
   * Scope of the saved config this draft's rule values were prefilled from, or
   * null when they are the organizer's own. Editor-only: an upsert stores
   * concrete values whatever their origin, so it never reaches the server.
   */
  inheritedFrom: PickBanInheritedScope | null;
}

export function emptyPickBanDraft(kind: PickBanKind): PickBanDraft {
  return {
    configId: null,
    kind,
    stageId: null,
    round: null,
    mode: "pool",
    orderMode: kind === "hero" ? "custom" : "bracket",
    firstBanRotation: "fixed",
    noRepeatScope: "none",
    turnTimerSeconds: null,
    allowProtect: false,
    uniqueRolePerRound: false,
    sequence: [],
    itemIds: [],
    slots: [],
    roundSlots: [],
    inheritedFrom: null,
  };
}

export function pickBanDraftFromConfig(config: PickBanConfig): PickBanDraft {
  return {
    configId: config.id,
    kind: config.kind,
    stageId: config.stage_id,
    round: config.round,
    mode: config.mode,
    // A hero config's steps are always hand-authored (see `effectiveSequence`),
    // whatever preset an older row happens to carry.
    orderMode: config.kind === "hero" || config.preset === CUSTOM_PRESET ? "custom" : "bracket",
    firstBanRotation: config.first_ban_rotation,
    noRepeatScope: config.no_repeat_scope,
    turnTimerSeconds: config.turn_timer_seconds,
    allowProtect: config.allow_protect,
    uniqueRolePerRound: config.unique_attribute_per_side_per_round === ROLE_ATTRIBUTE,
    sequence: [...config.sequence],
    itemIds: [...config.item_ids],
    slots: config.slots.map((slot) => ({
      candidates: [...slot.candidates],
      reserveItemId: slot.reserve_item_id,
    })),
    roundSlots: [],
    inheritedFrom: null,
  };
}

/**
 * The sequence a draft actually stores.
 *
 * Bracket order keeps a generated placeholder rather than an empty list: the
 * server validates `sequence` on every pool-mode upsert, and the engine
 * regenerates it per match anyway.
 *
 * A hero sequence is never generated: it is ONE round's steps, replayed for
 * every map of the series, while the generator answers a different question
 * ("how do we ban a pool of N down to `bestOf` maps") and emits picks and a
 * decider — steps a hero round cannot resolve, since its pool stays playable.
 */
export function effectiveSequence(
  draft: PickBanDraft,
  seriesLength: number
): PickBanSequenceToken[] {
  if (draft.mode === "slots") return [];
  if (draft.kind === "hero" || draft.orderMode === "custom") return draft.sequence;
  return buildSequenceForBestOf(seriesLength, draft.itemIds.length);
}

export function pickBanDraftToInput(
  draft: PickBanDraft,
  seriesLength: number
): PickBanConfigUpsertInput {
  const slotsMode = draft.mode === "slots";
  // A template's groups exist only because the bracket sized them; sending the
  // empty shells would trip the server's "a slot needs two candidates" rule,
  // where an empty list is accepted as "no pool here".
  const slots = slotsMode && !isRulesTemplate(draft) ? draft.slots : [];
  return {
    kind: draft.kind,
    stage_id: draft.stageId,
    round: draft.stageId != null ? draft.round : null,
    mode: draft.mode,
    first_ban_rotation: draft.firstBanRotation,
    // `ck_pick_ban_config_slots_not_custom` forbids the custom preset in slot
    // mode, where there is no hand-authored order to protect anyway.
    preset: slotsMode || (draft.kind !== "hero" && draft.orderMode === "bracket") ? BRACKET_PRESET : CUSTOM_PRESET,
    turn_timer_seconds: draft.turnTimerSeconds,
    no_repeat_scope: draft.noRepeatScope,
    unique_attribute_per_side_per_round:
      draft.kind === "hero" && draft.uniqueRolePerRound ? ROLE_ATTRIBUTE : null,
    allow_protect: draft.allowProtect,
    sequence: effectiveSequence(draft, seriesLength),
    item_ids: slotsMode ? [] : draft.itemIds,
    slots: slots.map((slot) => ({
      candidates: slot.candidates,
      reserve_item_id: slot.reserveItemId,
    })),
  };
}

/**
 * Whether this draft carries no candidates at all -- a rules TEMPLATE.
 *
 * The rules and the pool live in one row, so "set the rotation and the timer
 * once for the whole tournament, pick the maps per stage" used to be
 * unauthorable: the pool was required, and a tournament-wide pool is exactly
 * what a per-stage regulation does NOT have. A pool-less row is accepted
 * instead, and inherited downward by `rescopePickBanDraft` -- it opens no room
 * of its own (`PickBanSessionService._has_pool`).
 */
export function isRulesTemplate(draft: PickBanDraft): boolean {
  if (draft.mode !== "slots") return draft.itemIds.length === 0;
  const groups = draft.roundSlots.length > 0 ? draft.roundSlots.flatMap((round) => round.slots) : draft.slots;
  return groups.every((slot) => slot.candidates.length === 0);
}

// ── step tokens ──────────────────────────────────────────────────────────────

export interface PickBanStep {
  action: PickBanStepAction | "decider";
  /** Null only for `decider`. */
  side: PickBanStepSide | null;
}

export function parseStepToken(token: PickBanSequenceToken): PickBanStep {
  if (token === "decider") return { action: "decider", side: null };
  const [action, side] = token.split("_") as [PickBanStepAction, PickBanStepSide];
  return { action, side };
}

export function buildStepToken(
  action: PickBanStepAction | "decider",
  side: PickBanStepSide
): PickBanSequenceToken {
  return action === "decider" ? "decider" : (`${action}_${side}` as PickBanSequenceToken);
}

/** Rounds a sequence actually plays: every pick plus the decider. */
export function roundsPlayed(sequence: PickBanSequenceToken[]): number {
  return sequence.filter((token) => token !== "ban_first" && token !== "ban_second").length;
}

// ── scope ────────────────────────────────────────────────────────────────────

/**
 * A `<Select>` value for the scope row. Radix rejects an empty string, and
 * "tournament-wide" is not a stage id, so the two cases share one encoding.
 */
export const TOURNAMENT_SCOPE = "tournament";
/** A `<Select>` value for "every round of this stage". */
export const ALL_ROUNDS_SCOPE = "all";

export function encodeScope(stageId: number | null): string {
  return stageId == null ? TOURNAMENT_SCOPE : `stage:${stageId}`;
}

export function decodeScope(value: string): number | null {
  if (!value.startsWith("stage:")) return null;
  const id = Number(value.slice("stage:".length));
  return Number.isFinite(id) ? id : null;
}

// ── inheritance ──────────────────────────────────────────────────────────────

/**
 * The saved config a scope falls back to today, one level up: a round defers to
 * its stage's rules, and both defer to the tournament-wide set. Same ranking as
 * `resolve_config_at_level` server-side, minus the exact-scope match -- that one
 * is a collision (`findScopeCollision`), not an ancestor.
 */
export function findInheritedConfig(
  kind: PickBanKind,
  stageId: number | null,
  round: number | null,
  configs: PickBanConfig[]
): PickBanConfig | null {
  if (stageId == null) return null;
  const ofKind = configs.filter((config) => config.kind === kind);
  if (round != null) {
    const stageWide = ofKind.find((config) => config.stage_id === stageId && config.round == null);
    if (stageWide != null) return stageWide;
  }
  return ofKind.find((config) => config.stage_id == null && config.round == null) ?? null;
}

/**
 * Every value the editor authors, minus scope and identity: what "the same
 * rules" means.
 *
 * A bracket-order sequence is deliberately out. It is a placeholder the engine
 * regenerates per match from the series length (see `effectiveSequence`), so two
 * scopes that play by identical rules still store different tokens whenever
 * their brackets disagree on Bo.
 */
function ruleValues(draft: PickBanDraft): unknown[] {
  return [
    draft.mode,
    draft.orderMode,
    draft.firstBanRotation,
    draft.noRepeatScope,
    draft.turnTimerSeconds,
    draft.allowProtect,
    draft.uniqueRolePerRound,
    draft.kind === "hero" || draft.orderMode === "custom" ? draft.sequence : [],
    draft.itemIds,
    draft.slots.map((slot) => [slot.candidates, slot.reserveItemId]),
    draft.roundSlots.map((round) => [
      round.round,
      round.slots.map((slot) => [slot.candidates, slot.reserveItemId]),
    ]),
  ];
}

/** Do two drafts say the same thing about how a match is played? */
export function sameRuleValues(left: PickBanDraft, right: PickBanDraft): boolean {
  return JSON.stringify(ruleValues(left)) === JSON.stringify(ruleValues(right));
}

/**
 * `draft` moved to another scope, prefilled from whatever that scope inherits.
 *
 * Narrowing rules to a round is the common case, and retyping the tournament's
 * timer, rotation and pool onto every round of a bracket is the work organizers
 * skipped -- leaving rounds on rules they never meant. A new draft therefore
 * starts as a copy of the config its scope resolves to today, marked as such
 * (`inheritedFrom`), so the only edits left are the ones that differ.
 *
 * Values are never overwritten once they are someone's work: a saved config
 * keeps its own on a rescope, and so does a hand-authored new draft.
 */
export function rescopePickBanDraft(
  draft: PickBanDraft,
  stageId: number | null,
  round: number | null,
  configs: PickBanConfig[]
): PickBanDraft {
  const authored =
    draft.inheritedFrom == null && !sameRuleValues(draft, emptyPickBanDraft(draft.kind));
  if (draft.configId != null || authored) return { ...draft, stageId, round };

  const source = findInheritedConfig(draft.kind, stageId, round, configs);
  // Nothing to inherit here: values carried over from a scope this one no longer
  // sits under are nobody's choice, so they go rather than passing for one.
  if (source == null) return { ...emptyPickBanDraft(draft.kind), stageId, round };
  return {
    ...pickBanDraftFromConfig(source),
    configId: null,
    stageId,
    round,
    inheritedFrom: { stageId: source.stage_id, round: source.round },
  };
}

/** The encounter fields the round list and the series length read. */
export interface PickBanScopeEncounter {
  stage_id: number | null;
  round: number;
  best_of: number;
}

/**
 * The rounds an organizer can scope a config to, ascending; empty until the
 * bracket is generated.
 *
 * Deliberately does not guess before that: elimination round numbering isn't
 * simple enough for a local fallback to get right (double elimination's
 * lower bracket uses negative round numbers, and single elimination's round
 * count depends on team count, not a stage's independently-set
 * `max_rounds`), and a wrong guess would let an organizer scope a config to
 * a round the eventual bracket never has. `PickBanConfigsTab` asks the
 * server to predict the real numbers before generation instead
 * (`adminService.getStagePlannedRounds`), which runs the actual bracket
 * generator against the stage's planned team inputs.
 */
export function stageRoundOptions(
  stageId: number,
  encounters: PickBanScopeEncounter[] | undefined
): number[] {
  return [
    ...new Set(
      (encounters ?? [])
        .filter((encounter) => encounter.stage_id === stageId)
        .map((encounter) => encounter.round)
    ),
  ].sort((left, right) => left - right);
}

/** How confident the editor is about the series length it is previewing. */
type SeriesLengthSource = "round" | "stage" | "variesByRound" | "variesByMatch";

export interface SeriesLength {
  bestOf: number;
  source: SeriesLengthSource;
}

/**
 * The series length a scope plays, as the bracket defines it.
 *
 * Only `"round"` is exact. A stage-wide or tournament-wide config covers
 * matches of different lengths, so the value is a preview of the generated step
 * order, not a promise — the caller must label it as such.
 *
 * A round with no generated encounter yet goes through `projectStage`, the same
 * projection the bracket preview and the best-of editor read. Resolving it here
 * instead cost a Bo5 grand final three map groups rather than five: `final`
 * only outranks `default` when the caller says the round IS the final, and a
 * local `round === max_rounds` guess cannot say that — double elimination's
 * grand final is `upperRounds + 1` (derived from the team count), while
 * `max_rounds` is an independent planning field a new stage defaults to 5.
 */
export function resolveSeriesLength(
  stageId: number | null,
  round: number | null,
  stages: Stage[],
  encounters: PickBanScopeEncounter[] | undefined
): SeriesLength {
  if (stageId == null) return { bestOf: DEFAULT_BEST_OF, source: "variesByMatch" };

  if (round != null) {
    const generated = (encounters ?? []).find(
      (encounter) => encounter.stage_id === stageId && encounter.round === round
    );
    if (generated != null && generated.best_of > 0) {
      return { bestOf: generated.best_of, source: "round" };
    }
  }

  const stage = stages.find((candidate) => candidate.id === stageId);
  // A stage the caller does not know plays the default series.
  if (stage == null) {
    return { bestOf: DEFAULT_BEST_OF, source: round != null ? "round" : "stage" };
  }

  if (round != null) {
    const projected = projectStage({
      stage,
      stages,
      stageType: stage.stage_type,
      splitLowerBracket: stage.split_lower_bracket,
      maxRounds: stage.max_rounds,
      bestOf: stage.best_of,
    }).rounds.find((candidate) => candidate.round === round);
    if (projected != null) return { bestOf: projected.bestOf, source: "round" };
  }

  const bestOf = resolveBestOf(stage.best_of, round ?? 1, {
    isFinal: round != null && round === stage.max_rounds,
  });
  if (round != null) return { bestOf, source: "round" };
  return { bestOf, source: hasPerRoundBestOf(stage.best_of) ? "variesByRound" : "stage" };
}

/**
 * How many round groups a slot-mode pool needs here, from the bracket.
 *
 * The count is never the organizer's to type: the server plays the first
 * `best_of` groups and keeps the room shut when the pool has fewer, so a group
 * count that disagrees with the bracket is always a misconfiguration. Groups
 * past the longest series a scope covers are dead weight the server ignores,
 * which is why this is a max and not `resolveSeriesLength`'s single preview: a
 * stage-wide pool has to cover its Bo5 final as well as its Bo3 rounds.
 */
export function resolveSlotCount(
  stageId: number | null,
  round: number | null,
  stages: Stage[],
  encounters: PickBanScopeEncounter[] | undefined
): number {
  if (stageId != null && round != null) {
    return resolveSeriesLength(stageId, round, stages, encounters).bestOf;
  }

  // Generated encounters are the truth once the bracket exists; the stage's
  // configuration is the only thing to go on before it does.
  const generated = (encounters ?? [])
    .filter((encounter) => stageId == null || encounter.stage_id === stageId)
    .map((encounter) => encounter.best_of)
    .filter((bestOf) => bestOf > 0);
  if (generated.length > 0) return Math.max(...generated);

  const planned = (stageId == null ? stages : stages.filter((stage) => stage.id === stageId)).map(
    (stage) => maxBestOf(stage.best_of)
  );
  return planned.length > 0 ? Math.max(...planned) : DEFAULT_BEST_OF;
}

/** A slot list resized to `count`, keeping every group the new size still has. */
export function alignSlots(
  slots: PickBanDraft["slots"],
  count: number
): PickBanDraft["slots"] {
  if (slots.length === count) return slots;
  return Array.from(
    { length: count },
    (_, index) => slots[index] ?? { candidates: [], reserveItemId: null }
  );
}

/**
 * The groups of every round of a stage, for the stage screen.
 *
 * A round that already has its own slot-mode config is authored from it; the
 * rest start as a copy of `fallback` — the groups the stage itself stores, or
 * whatever it inherits — because "the same pool everywhere" is where a
 * per-round pool is edited from, not a blank page. Each round is sized by
 * `slotCountFor`, since a stage's final can be longer than its other rounds.
 */
export function roundSlotsForStage({
  kind,
  stageId,
  rounds,
  configs,
  fallback,
  slotCountFor,
}: {
  kind: PickBanKind;
  stageId: number;
  rounds: number[];
  configs: PickBanConfig[];
  fallback: PickBanDraftSlot[];
  slotCountFor: (round: number) => number;
}): PickBanDraftRoundSlots[] {
  return rounds.map((round) => {
    const own = configs.find(
      (config) =>
        config.kind === kind &&
        config.stage_id === stageId &&
        config.round === round &&
        config.mode === "slots"
    );
    const slots =
      own != null
        ? own.slots.map((slot) => ({
            candidates: [...slot.candidates],
            reserveItemId: slot.reserve_item_id,
          }))
        : fallback.map((slot) => ({ ...slot, candidates: [...slot.candidates] }));
    return { round, slots: alignSlots(slots, slotCountFor(round)) };
  });
}

/**
 * One draft per round of a stage-wide slot draft: the same rules, that round's
 * groups, scoped to that round.
 *
 * The store has no round dimension inside a config (`ck` on `(stage, round)`),
 * so a per-round pool is N configs and a save is N upserts. Nothing is written
 * at the stage level: a stage-wide config would be shadowed by every one of
 * them anyway.
 */
export function fanOutRoundDrafts(draft: PickBanDraft): PickBanDraft[] {
  if (draft.mode !== "slots" || draft.roundSlots.length === 0) return [draft];
  return draft.roundSlots.map((round) => ({
    ...draft,
    configId: null,
    round: round.round,
    slots: round.slots,
    roundSlots: [],
  }));
}

// ── validation ───────────────────────────────────────────────────────────────

/**
 * A rejection the editor can actually produce, as data: `key` resolves under
 * `pickBan.admin.validation.*` and `values` feeds its ICU arguments.
 *
 * Mirrors `validate_pick_ban_config` / `validate_pick_ban_slot_config`, minus
 * the rejections this editor makes unreachable — ids come from toggles, so they
 * can neither repeat nor be unparseable, and a reserve picker never offers its
 * own slot's candidates.
 */
export type PickBanValidationIssue =
  | { key: "emptySequence"; values?: undefined }
  | { key: "multipleDeciders"; values?: undefined }
  | { key: "deciderNotLast"; values?: undefined }
  | { key: "noPickOrDecider"; values?: undefined }
  | { key: "heroDecider"; values?: undefined }
  | { key: "sequenceLongerThanPool"; values: { steps: number; items: number } }
  | { key: "slotTooFewCandidates"; values: { slot: number } }
  | { key: "roundSlotTooFewCandidates"; values: { round: number; slot: number } };

export function validatePickBanDraft(
  draft: PickBanDraft,
  seriesLength: number
): PickBanValidationIssue[] {
  // A pool-less draft is a rules template (`isRulesTemplate`): the server takes
  // it, and the pool-shaped rules -- a sequence that fits inside the pool, two
  // candidates per group -- have nothing to hold. What it cannot do is open a
  // room, which the editor says outright rather than as a validation error.
  if (isRulesTemplate(draft)) return [];
  if (draft.mode === "slots") {
    // A stage-wide draft authors every round of the stage at once; each round
    // is saved as its own config, so each one has to stand on its own.
    if (draft.roundSlots.length > 0) {
      return draft.roundSlots.flatMap((round) =>
        round.slots.flatMap((slot, index) =>
          slot.candidates.length < SLOT_CANDIDATE_FLOOR
            ? [
                {
                  key: "roundSlotTooFewCandidates" as const,
                  values: { round: round.round, slot: index + 1 },
                },
              ]
            : []
        )
      );
    }
    // An empty group list cannot reach here: no candidates anywhere IS a
    // template, handled above.
    return draft.slots.flatMap((slot, index) =>
      slot.candidates.length < SLOT_CANDIDATE_FLOOR
        ? [{ key: "slotTooFewCandidates" as const, values: { slot: index + 1 } }]
        : []
    );
  }

  const issues: PickBanValidationIssue[] = [];

  const sequence = effectiveSequence(draft, seriesLength);
  if (sequence.length === 0) {
    // Reachable in custom order only: bracket order generates from the pool,
    // and an empty pool is already reported above.
    if (draft.itemIds.length > 0) issues.push({ key: "emptySequence" });
  } else if (draft.kind === "hero") {
    // A hero round bans out of a pool that stays playable, so there is no
    // survivor for a decider to resolve to, and no "must end in a pick" rule
    // to satisfy either (mirrors `validate_pick_ban_config`'s hero branch).
    if (sequence.includes("decider")) issues.push({ key: "heroDecider" });
  } else {
    const deciders = sequence.filter((token) => token === "decider").length;
    if (deciders > 1) {
      issues.push({ key: "multipleDeciders" });
    } else if (deciders === 1 && sequence[sequence.length - 1] !== "decider") {
      issues.push({ key: "deciderNotLast" });
    }
    if (!sequence.some((token) => token.startsWith("pick") || token === "decider")) {
      issues.push({ key: "noPickOrDecider" });
    }
  }

  if (draft.itemIds.length > 0 && sequence.length > draft.itemIds.length) {
    issues.push({
      key: "sequenceLongerThanPool",
      values: { steps: sequence.length, items: draft.itemIds.length },
    });
  }
  return issues;
}

/**
 * Whether `allowProtect` is on but no step will ever run it.
 *
 * The toggle alone changes nothing: the engine only offers a protect action
 * where the resolved sequence carries a `protect_*` token, and a
 * bracket-generated order never does. Surfaced as a notice rather than a
 * validation error, because the server accepts the combination.
 */
export function protectHasNoStep(draft: PickBanDraft, seriesLength: number): boolean {
  if (!draft.allowProtect) return false;
  if (draft.mode === "slots") return true;
  return !effectiveSequence(draft, seriesLength).some((token) => token.startsWith("protect"));
}

/** The existing config a draft would overwrite on save, if any. */
export function findScopeCollision(
  draft: PickBanDraft,
  configs: PickBanConfig[]
): PickBanConfig | null {
  const round = draft.stageId != null ? draft.round : null;
  return (
    configs.find(
      (config) =>
        config.id !== draft.configId &&
        config.kind === draft.kind &&
        config.stage_id === draft.stageId &&
        config.round === round
    ) ?? null
  );
}

// ── catalogue search ─────────────────────────────────────────────────────────

/** Diacritic- and curly-quote-insensitive, case-folded form of a catalogue name. */
function normalizeItemName(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\u2019/g, "'")
    .toLowerCase();
}

/**
 * Does `query` name `name`? Used by the map and hero pickers, where an
 * organizer types what a paper regulation or cast calls a map/hero rather
 * than the catalogue's exact spelling. A plain substring test alone misses
 * two common mismatches; an empty query matches everything.
 */
export function matchesItemName(name: string, query: string): boolean {
  const needle = normalizeItemName(query).trim();
  if (needle === "") return true;
  const haystack = normalizeItemName(name);
  // "Shambali" for "Shambali Monastery": the query drops a trailing word.
  if (haystack.includes(needle)) return true;
  // "Peninsular" for "Antarctic Peninsula": the query adds letters to a word
  // the catalogue carries, which no substring test reaches from either side.
  // Accept a query one of the name's words is a prefix of, from three
  // characters up so a short word cannot drag in unrelated entries.
  return haystack.split(/\s+/).some((word) => word.length >= 3 && needle.startsWith(word));
}
