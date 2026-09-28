/**
 * Form model of one `PickBanConfig`, and the pure logic the editor needs.
 *
 * The rules themselves are a `PickBanRuleset` (ruleset v2,
 * docs/plans/2026-09-28-pick-ban-constructor.md §1): phases decide which steps
 * run on which map of the series, steps carry actors/count/blind/target/
 * lifetime/timer/dispute, and condition trees decide what may be chosen. The
 * draft holds that document verbatim — there is no second, flatter form model
 * to keep in step with it, and the server validates the same JSON it is sent.
 *
 * What the draft still owns beyond the ruleset is the scope key, the pool
 * (`item_ids` or slot groups) and the rotation, because those are not rules
 * about *how* a round is played.
 *
 * `first_pick_rule` is omitted entirely: its type has exactly one member, and
 * the server defaults to it, so a control would be a dead choice.
 *
 * `inheritedFrom` runs the other way: form-only, never sent. It records which
 * saved config a new draft's values were prefilled from (`rescopePickBanDraft`),
 * so the editor can say where they came from instead of presenting a copy of the
 * tournament's rules as if the organizer had typed it.
 */
import { DEFAULT_BEST_OF, hasPerRoundBestOf, maxBestOf, resolveBestOf } from "@/lib/tournament/best-of";
import { projectStage } from "@/lib/bracket/projection";
import type {
  MapVetoMode,
  PickBanActors,
  PickBanCondition,
  PickBanConfig,
  PickBanConfigUpsertInput,
  PickBanFirstBanRotation,
  PickBanKind,
  PickBanRuleset,
  PickBanRulesetPhase,
  PickBanRulesetStep,
  PickBanStepAction,
  PickBanTimeoutPolicy,
  Stage,
} from "@/types/tournament.types";

/** Candidates a slot needs to ban down to a survivor. Mirrors `pick_ban_session.SLOT_CANDIDATE_FLOOR`. */
const SLOT_CANDIDATE_FLOOR = 2;

export const PICK_BAN_MODES: MapVetoMode[] = ["pool", "slots"];
export const PICK_BAN_ROTATIONS: PickBanFirstBanRotation[] = [
  "fixed",
  "alternate",
  "result_winner_first",
  "result_loser_first",
  "result_loser_choice",
];

/** Every actor resolution the engine implements, in menu order (§1). */
export const PICK_BAN_ACTORS: PickBanActors[] = [
  "first",
  "second",
  "both",
  "home",
  "away",
  "winner_prev",
  "loser_prev",
  "system",
];

export const PICK_BAN_STEP_ACTIONS: PickBanStepAction[] = ["ban", "pick", "protect", "decider"];
export const PICK_BAN_TIMEOUTS: PickBanTimeoutPolicy[] = ["random_fill", "lock_draft", "wait"];

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
  firstBanRotation: PickBanFirstBanRotation;
  /** The whole rules document, exactly as it is stored and validated. */
  ruleset: PickBanRuleset;
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

// ── ruleset factories ────────────────────────────────────────────────────────

/** The default step timer a new ruleset offers, in seconds (§12 uses 90). */
export const DEFAULT_TIMER_SECONDS = 90;

/**
 * A fresh ruleset for `kind`, in the shape that reproduces what the scope used
 * to do by default.
 *
 * A map ruleset opens on the bracket generator — the server builds the veto
 * order from the pool and the series length, which is what every map config
 * did before the constructor existed. A hero ruleset has no generator (a hero
 * pool stays playable, so there is nothing to ban down to) and opens on one
 * empty phase the organizer fills from the step palette.
 */
export function emptyRuleset(kind: PickBanKind, mode: MapVetoMode = "pool"): PickBanRuleset {
  return {
    version: 2,
    timer_seconds: null,
    on_timeout: "random_fill",
    phases: [
      {
        id: "main",
        name: null,
        when: {},
        pool_filter: {},
        generator: kind === "map" ? (mode === "slots" ? "slot_veto" : "bracket") : null,
        steps: [],
      },
    ],
  };
}

/**
 * Mints ids no phase or step of `ruleset` carries, and remembers what it just
 * handed out — duplicating a phase needs several at once.
 */
function idAllocator(ruleset: PickBanRuleset): (prefix: string) => string {
  const taken = new Set<string>(
    ruleset.phases.flatMap((phase) => [phase.id, ...phase.steps.map((step) => step.id)])
  );
  return (prefix) => {
    for (let index = 1; ; index += 1) {
      const candidate = `${prefix}${index}`;
      if (!taken.has(candidate)) {
        taken.add(candidate);
        return candidate;
      }
    }
  };
}

export function newPhase(ruleset: PickBanRuleset): PickBanRulesetPhase {
  return {
    id: idAllocator(ruleset)("phase"),
    name: null,
    when: {},
    pool_filter: {},
    generator: null,
    steps: [],
  };
}

/**
 * The step shapes the palette offers (§13). Each is a real step with the
 * defaults of §1 filled in — a "simultaneous blind ban" is not a mode, it is
 * `actors: both, blind: true`, and the palette exists so an organizer does not
 * have to know that.
 */
export type PickBanStepTemplate =
  | "ban_sequential"
  | "ban_blind"
  | "ban_per_player"
  | "pick"
  | "protect"
  | "decider"
  | "roulette";

export const PICK_BAN_STEP_TEMPLATES: PickBanStepTemplate[] = [
  "ban_sequential",
  "ban_blind",
  "ban_per_player",
  "pick",
  "protect",
  "decider",
  "roulette",
];

/** The bare step every template starts from: one item, open, this map only. */
function baseStep(id: string): PickBanRulesetStep {
  return {
    id,
    action: "ban",
    actors: "first",
    count: 1,
    min: null,
    blind: false,
    target: null,
    lifetime: 1,
    timer_seconds: null,
    on_timeout: null,
    dispute: { enabled: false, max: 0 },
    eligible: {},
    constraints: [],
  };
}

export function newStep(ruleset: PickBanRuleset, template: PickBanStepTemplate): PickBanRulesetStep {
  const step = baseStep(idAllocator(ruleset)("step"));
  switch (template) {
    case "ban_sequential":
      return step;
    case "ban_blind":
      return { ...step, actors: "both", count: 2, blind: true, dispute: { enabled: true, max: 1 } };
    case "ban_per_player":
      // The 2026-10-03 anti-one-trick shape (§12): one ban per opponent player,
      // hero class matching that player's role, alive for two maps.
      return {
        ...step,
        actors: "both",
        count: 5,
        blind: true,
        target: "opponent_player",
        lifetime: 2,
        dispute: { enabled: true, max: 1 },
        eligible: { type: "target_role_match", params: {} },
        constraints: [{ type: "one_per_target", params: {} }],
      };
    case "pick":
      // A pick settles a map of the series; it has no lifetime to expire.
      return { ...step, action: "pick", lifetime: null };
    case "protect":
      return { ...step, action: "protect", lifetime: null };
    case "decider":
      return { ...step, action: "decider", actors: "system", lifetime: null };
    case "roulette":
      // A system ban: the engine rolls it, nobody acts.
      return { ...step, actors: "system" };
  }
}

// ── ruleset editing ──────────────────────────────────────────────────────────

/** `list` with the item at `index` moved by `delta`, or unchanged at an edge. */
function moved<T>(list: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function updatePhase(
  ruleset: PickBanRuleset,
  phaseId: string,
  patch: Partial<PickBanRulesetPhase>
): PickBanRuleset {
  return {
    ...ruleset,
    phases: ruleset.phases.map((phase) => (phase.id === phaseId ? { ...phase, ...patch } : phase)),
  };
}

export function movePhase(ruleset: PickBanRuleset, phaseId: string, delta: number): PickBanRuleset {
  const index = ruleset.phases.findIndex((phase) => phase.id === phaseId);
  if (index < 0) return ruleset;
  return { ...ruleset, phases: moved(ruleset.phases, index, delta) };
}

export function removePhase(ruleset: PickBanRuleset, phaseId: string): PickBanRuleset {
  return { ...ruleset, phases: ruleset.phases.filter((phase) => phase.id !== phaseId) };
}

export function duplicatePhase(ruleset: PickBanRuleset, phaseId: string): PickBanRuleset {
  const index = ruleset.phases.findIndex((phase) => phase.id === phaseId);
  if (index < 0) return ruleset;
  const source = ruleset.phases[index];
  // Ids are unique across the whole ruleset, so the copy's steps are renamed
  // too — a duplicate that shared step ids would make `resolved_sequence_json`
  // ambiguous about which phase a step came from.
  const nextId = idAllocator(ruleset);
  const copy: PickBanRulesetPhase = {
    ...source,
    id: nextId("phase"),
    steps: source.steps.map((step) => ({ ...step, id: nextId("step") })),
  };
  const phases = [...ruleset.phases];
  phases.splice(index + 1, 0, copy);
  return { ...ruleset, phases };
}

export function addStep(
  ruleset: PickBanRuleset,
  phaseId: string,
  template: PickBanStepTemplate
): PickBanRuleset {
  const step = newStep(ruleset, template);
  return updatePhaseSteps(ruleset, phaseId, (steps) => [...steps, step]);
}

export function updateStep(
  ruleset: PickBanRuleset,
  phaseId: string,
  stepId: string,
  patch: Partial<PickBanRulesetStep>
): PickBanRuleset {
  return updatePhaseSteps(ruleset, phaseId, (steps) =>
    steps.map((step) => (step.id === stepId ? { ...step, ...patch } : step))
  );
}

export function moveStep(
  ruleset: PickBanRuleset,
  phaseId: string,
  stepId: string,
  delta: number
): PickBanRuleset {
  return updatePhaseSteps(ruleset, phaseId, (steps) => {
    const index = steps.findIndex((step) => step.id === stepId);
    return index < 0 ? steps : moved(steps, index, delta);
  });
}

export function removeStep(ruleset: PickBanRuleset, phaseId: string, stepId: string): PickBanRuleset {
  return updatePhaseSteps(ruleset, phaseId, (steps) => steps.filter((step) => step.id !== stepId));
}

export function duplicateStep(
  ruleset: PickBanRuleset,
  phaseId: string,
  stepId: string
): PickBanRuleset {
  const id = idAllocator(ruleset)("step");
  return updatePhaseSteps(ruleset, phaseId, (steps) => {
    const index = steps.findIndex((step) => step.id === stepId);
    if (index < 0) return steps;
    const copy = [...steps];
    copy.splice(index + 1, 0, { ...steps[index], id });
    return copy;
  });
}

function updatePhaseSteps(
  ruleset: PickBanRuleset,
  phaseId: string,
  edit: (steps: PickBanRulesetStep[]) => PickBanRulesetStep[]
): PickBanRuleset {
  return {
    ...ruleset,
    phases: ruleset.phases.map((phase) =>
      phase.id === phaseId ? { ...phase, steps: edit(phase.steps) } : phase
    ),
  };
}

/** Is this condition tree "anything"? `{}` is the DSL's always-true. */
export function isEmptyCondition(condition: PickBanCondition): boolean {
  return Object.keys(condition ?? {}).length === 0;
}

/**
 * How one step reads on its card: a message key under `pickBan.rules.summary`
 * plus its ICU arguments.
 *
 * Data rather than a string because the editor is translated and the summary is
 * the one place a whole step has to be legible at a glance.
 */
export function stepSummary(step: PickBanRulesetStep): {
  key: "open" | "blind" | "perTarget";
  values: Record<string, string | number>;
} {
  if (step.target != null) {
    return { key: "perTarget", values: { count: step.count } };
  }
  if (step.blind) {
    return { key: "blind", values: { count: step.count } };
  }
  return { key: "open", values: { count: step.count } };
}

/**
 * How long one step's bans stay in force, as a message key under
 * `pickBan.rules.summary` — or null when the step has no lifetime to speak of.
 *
 * Only a ban expires; a pick, a protect and a decider settle something and are
 * done. Worth its own line on the card because it is the parameter an
 * organizer cannot infer: a five-ban step that holds for two maps is twenty
 * heroes gone by map 3, and nothing else on the card says so.
 */
export function stepLifetimeSummary(
  step: PickBanRulesetStep
): { key: "lifetimeMaps" | "lifetimeSeries"; values: Record<string, number> } | null {
  if (step.action !== "ban") return null;
  if (step.lifetime == null) return { key: "lifetimeSeries", values: {} };
  return { key: "lifetimeMaps", values: { count: step.lifetime } };
}

/**
 * A ruleset parsed out of pasted JSON, or null when the text is not one.
 *
 * A shape check, not a validator: the server is the authority on whether a
 * ruleset is playable (`validateRuleset`), and re-implementing §2's grammar
 * here would be a second opinion that can only drift. What this rejects is
 * text that would crash the editor before the server ever sees it.
 */
export function parseRulesetJson(text: string): PickBanRuleset | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (data == null || typeof data !== "object") return null;
  const candidate = data as Partial<PickBanRuleset>;
  if (candidate.version !== 2 || !Array.isArray(candidate.phases)) return null;
  if (
    !candidate.phases.every(
      (phase) =>
        phase != null &&
        typeof phase === "object" &&
        typeof phase.id === "string" &&
        Array.isArray(phase.steps)
    )
  ) {
    return null;
  }
  return {
    version: 2,
    timer_seconds: typeof candidate.timer_seconds === "number" ? candidate.timer_seconds : null,
    on_timeout: candidate.on_timeout ?? "random_fill",
    phases: candidate.phases,
  };
}

// ── draft ────────────────────────────────────────────────────────────────────

export function emptyPickBanDraft(kind: PickBanKind): PickBanDraft {
  return {
    configId: null,
    kind,
    stageId: null,
    round: null,
    mode: "pool",
    firstBanRotation: "fixed",
    ruleset: emptyRuleset(kind),
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
    firstBanRotation: config.first_ban_rotation,
    ruleset: config.ruleset,
    itemIds: [...config.item_ids],
    slots: config.slots.map((slot) => ({
      candidates: [...slot.candidates],
      reserveItemId: slot.reserve_item_id,
    })),
    roundSlots: [],
    inheritedFrom: null,
  };
}

export function pickBanDraftToInput(draft: PickBanDraft): PickBanConfigUpsertInput {
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
    ruleset: draft.ruleset,
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
 */
function ruleValues(draft: PickBanDraft): unknown[] {
  return [
    draft.mode,
    draft.firstBanRotation,
    draft.ruleset,
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
 * A rejection the editor can produce without asking the server, as data: `key`
 * resolves under `pickBan.admin.validation.*` and `values` feeds its ICU
 * arguments.
 *
 * Deliberately shallow. Everything about the ruleset itself — unknown leaves,
 * wrong contexts, counts past the pool, a map index no phase covers — is
 * `validateRuleset`'s answer (§6), and a second opinion here could only drift
 * from the engine that actually runs the draft. What is left is the pool
 * shape, which the editor owns outright, plus the two ways a ruleset can be
 * empty enough that no round would ever run.
 */
export type PickBanValidationIssue =
  | { key: "noPhases"; values?: undefined }
  | { key: "phaseWithoutSteps"; values: { phase: string } }
  | { key: "slotTooFewCandidates"; values: { slot: number } }
  | { key: "roundSlotTooFewCandidates"; values: { round: number; slot: number } };

export function validatePickBanDraft(draft: PickBanDraft): PickBanValidationIssue[] {
  const issues: PickBanValidationIssue[] = [];

  if (draft.ruleset.phases.length === 0) {
    issues.push({ key: "noPhases" });
  }
  for (const phase of draft.ruleset.phases) {
    // A generator phase has no steps by construction: the server expands it.
    if (phase.generator == null && phase.steps.length === 0) {
      issues.push({ key: "phaseWithoutSteps", values: { phase: phase.name ?? phase.id } });
    }
  }

  // A pool-less draft is a rules template (`isRulesTemplate`): the server takes
  // it, and the pool-shaped rules have nothing to hold. What it cannot do is
  // open a room, which the editor says outright rather than as an error.
  if (isRulesTemplate(draft) || draft.mode !== "slots") return issues;

  // A stage-wide draft authors every round of the stage at once; each round is
  // saved as its own config, so each one has to stand on its own.
  if (draft.roundSlots.length > 0) {
    for (const round of draft.roundSlots) {
      round.slots.forEach((slot, index) => {
        if (slot.candidates.length < SLOT_CANDIDATE_FLOOR) {
          issues.push({
            key: "roundSlotTooFewCandidates",
            values: { round: round.round, slot: index + 1 },
          });
        }
      });
    }
    return issues;
  }

  draft.slots.forEach((slot, index) => {
    if (slot.candidates.length < SLOT_CANDIDATE_FLOOR) {
      issues.push({ key: "slotTooFewCandidates", values: { slot: index + 1 } });
    }
  });
  return issues;
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
