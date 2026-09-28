// The form model of one `PickBanConfig` under ruleset v2.
//
// What is pinned here is the behaviour an organizer can lose: the ruleset the
// editor holds is the ruleset that is SENT (the v1 model had three wire fields
// that silently discarded a hand-authored order, which is the class of bug this
// file exists to prevent); ids stay unique through duplication, so a copied
// phase cannot shadow the one it came from; the cascade prefills a narrower
// scope from what it inherits; and the pool shape the editor owns is validated
// before a 422.
import { describe, expect, it } from "vitest";

import type { PickBanConfig, PickBanRuleset, Stage } from "@/types/tournament.types";

import {
  addStep,
  alignSlots,
  duplicatePhase,
  duplicateStep,
  emptyPickBanDraft,
  emptyRuleset,
  fanOutRoundDrafts,
  findScopeCollision,
  isRulesTemplate,
  moveStep,
  newPhase,
  newStep,
  parseRulesetJson,
  pickBanDraftFromConfig,
  pickBanDraftToInput,
  removeStep,
  rescopePickBanDraft,
  resolveSeriesLength,
  resolveSlotCount,
  roundSlotsForStage,
  stageRoundOptions,
  stepLifetimeSummary,
  stepSummary,
  updateStep,
  validatePickBanDraft,
  type PickBanDraft,
} from "@/lib/tournament/pick-ban-config";

/** The 2026-10-03 anti-one-trick ruleset (plan §12), trimmed to one phase. */
const BLIND_RULESET: PickBanRuleset = {
  version: 2,
  timer_seconds: 90,
  on_timeout: "random_fill",
  phases: [
    {
      id: "map1",
      name: "Map 1",
      when: { type: "map_index", params: { op: "==", value: 1 } },
      pool_filter: {},
      generator: null,
      steps: [
        {
          id: "blind2",
          action: "ban",
          actors: "both",
          count: 2,
          min: null,
          blind: true,
          target: null,
          lifetime: 1,
          timer_seconds: null,
          on_timeout: null,
          dispute: { enabled: true, max: 1 },
          eligible: {},
          constraints: [],
        },
      ],
    },
  ],
};

function draft(overrides: Partial<PickBanDraft> = {}): PickBanDraft {
  return { ...emptyPickBanDraft("map"), itemIds: [1, 2, 3, 4, 5], ...overrides };
}

function stage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Playoffs",
    description: null,
    stage_type: "single_elimination",
    max_rounds: 3,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: true,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items: [],
    ...overrides,
  } as Stage;
}

function config(overrides: Partial<PickBanConfig> = {}): PickBanConfig {
  return {
    id: 1,
    tournament_id: 84,
    kind: "map",
    stage_id: null,
    round: null,
    mode: "pool",
    first_pick_rule: "higher_seed",
    first_ban_rotation: "fixed",
    ruleset: emptyRuleset("map"),
    item_ids: [1, 2, 3, 4, 5],
    slots: [],
    ...overrides,
  };
}

describe("the ruleset the editor holds is the ruleset that is sent", () => {
  it("ships the edited ruleset verbatim, not a shape derived from it", () => {
    const input = pickBanDraftToInput(draft({ kind: "hero", ruleset: BLIND_RULESET }));

    expect(input.ruleset).toEqual(BLIND_RULESET);
    expect(input.kind).toBe("hero");
  });

  it("round-trips a stored ruleset back out unchanged", () => {
    const restored = pickBanDraftFromConfig(config({ kind: "hero", ruleset: BLIND_RULESET }));

    expect(pickBanDraftToInput(restored).ruleset).toEqual(BLIND_RULESET);
  });

  it("opens a map config on the bracket generator, which is what v1 configs did", () => {
    // Every map config used to regenerate its order from the pool and the
    // series length; the generator phase is that behaviour, spelled out.
    expect(emptyRuleset("map").phases[0].generator).toBe("bracket");
    expect(emptyRuleset("map", "slots").phases[0].generator).toBe("slot_veto");
    // A hero pool stays playable, so there is nothing to generate down to.
    expect(emptyRuleset("hero").phases[0].generator).toBeNull();
  });

  it("drops a round that no stage scopes it, which the server rejects", () => {
    // `admin_pick_ban_config_upsert`: "round requires stage_id".
    expect(pickBanDraftToInput(draft({ stageId: null, round: 4 })).round).toBeNull();
    expect(pickBanDraftToInput(draft({ stageId: 10, round: 4 })).round).toBe(4);
  });

  it("never sends slot groups and a flat pool at once", () => {
    const input = pickBanDraftToInput(
      draft({ mode: "slots", slots: [{ candidates: [1, 2], reserveItemId: null }] })
    );

    expect(input.item_ids).toEqual([]);
    expect(input.slots).toEqual([{ candidates: [1, 2], reserve_item_id: null }]);
  });
});

describe("the step palette writes real steps", () => {
  const base = emptyRuleset("hero");

  it("makes a simultaneous blind ban both sides act at once, privately", () => {
    const step = newStep(base, "ban_blind");

    expect(step).toMatchObject({ action: "ban", actors: "both", blind: true, count: 2 });
    // A blind step is the one an opponent can ask to redo after the reveal.
    expect(step.dispute.enabled).toBe(true);
  });

  it("makes a per-player ban target a player, one each, matching their role", () => {
    const step = newStep(base, "ban_per_player");

    expect(step.target).toBe("opponent_player");
    expect(step.lifetime).toBe(2);
    expect(step.eligible).toEqual({ type: "target_role_match", params: {} });
    expect(step.constraints).toEqual([{ type: "one_per_target", params: {} }]);
  });

  it("leaves a pick and a decider without a ban lifetime to expire", () => {
    expect(newStep(base, "pick").lifetime).toBeNull();
    expect(newStep(base, "decider")).toMatchObject({ action: "decider", actors: "system" });
    // The roulette is a ban nobody takes: the engine rolls it.
    expect(newStep(base, "roulette")).toMatchObject({ action: "ban", actors: "system" });
  });

  // The step card is the only place a whole step is legible at a glance, and
  // the lifetime is the parameter an organizer cannot infer from the rest: a
  // five-ban step holding for two maps is twenty heroes gone by map 3.
  it("says on the card how many items a step takes, and how long its bans hold", () => {
    expect(stepSummary(newStep(base, "ban_per_player"))).toEqual({
      key: "perTarget",
      values: { count: 5 },
    });
    expect(stepSummary(newStep(base, "ban_blind"))).toEqual({
      key: "blind",
      values: { count: 2 },
    });
    expect(stepSummary(newStep(base, "ban_sequential"))).toEqual({
      key: "open",
      values: { count: 1 },
    });

    expect(stepLifetimeSummary(newStep(base, "ban_per_player"))).toEqual({
      key: "lifetimeMaps",
      values: { count: 2 },
    });
    expect(
      stepLifetimeSummary({ ...newStep(base, "ban_sequential"), lifetime: null })
    ).toEqual({ key: "lifetimeSeries", values: {} });
    // Only a ban expires; a pick settles a map and is done.
    expect(stepLifetimeSummary(newStep(base, "pick"))).toBeNull();
    expect(stepLifetimeSummary(newStep(base, "decider"))).toBeNull();
  });
});

describe("ids stay unique, so no two steps can claim the same resolved slot", () => {
  it("never reuses an id a phase or a step already carries", () => {
    let ruleset = addStep(emptyRuleset("hero"), "main", "ban_blind");
    ruleset = addStep(ruleset, "main", "pick");
    const second = newPhase(ruleset);

    const ids = [
      ...ruleset.phases.map((phase) => phase.id),
      ...ruleset.phases.flatMap((phase) => phase.steps.map((step) => step.id)),
      second.id,
    ];
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("renames every step of a duplicated phase", () => {
    const ruleset = duplicatePhase(addStep(emptyRuleset("hero"), "main", "ban_blind"), "main");

    expect(ruleset.phases).toHaveLength(2);
    const ids = ruleset.phases.flatMap((phase) => [phase.id, ...phase.steps.map((s) => s.id)]);
    expect(new Set(ids).size).toBe(ids.length);
    // The copy is the same rules, placed right after the original.
    expect(ruleset.phases[1].steps[0]).toMatchObject({ actors: "both", blind: true });
  });

  it("places a duplicated step directly after the one it copies", () => {
    let ruleset = addStep(emptyRuleset("hero"), "main", "ban_sequential");
    ruleset = addStep(ruleset, "main", "pick");
    const firstId = ruleset.phases[0].steps[0].id;

    const steps = duplicateStep(ruleset, "main", firstId).phases[0].steps;

    expect(steps.map((step) => step.action)).toEqual(["ban", "ban", "pick"]);
    expect(steps[1].id).not.toBe(firstId);
  });
});

describe("reordering and editing steps", () => {
  let ruleset = addStep(emptyRuleset("hero"), "main", "ban_sequential");
  ruleset = addStep(ruleset, "main", "pick");
  const [first, second] = ruleset.phases[0].steps.map((step) => step.id);

  it("swaps a step with its neighbour and stops at the edges", () => {
    expect(moveStep(ruleset, "main", second, -1).phases[0].steps.map((s) => s.id)).toEqual([
      second,
      first,
    ]);
    expect(moveStep(ruleset, "main", first, -1).phases[0].steps.map((s) => s.id)).toEqual([
      first,
      second,
    ]);
  });

  it("patches one step and leaves its siblings alone", () => {
    const edited = updateStep(ruleset, "main", first, { count: 3, actors: "both" });

    expect(edited.phases[0].steps[0]).toMatchObject({ count: 3, actors: "both" });
    expect(edited.phases[0].steps[1]).toEqual(ruleset.phases[0].steps[1]);
  });

  it("removes a step without touching the rest of the ruleset", () => {
    const trimmed = removeStep(ruleset, "main", first);

    expect(trimmed.phases[0].steps.map((step) => step.id)).toEqual([second]);
    expect(trimmed.timer_seconds).toBe(ruleset.timer_seconds);
  });
});

describe("pasted JSON", () => {
  it("accepts a ruleset an organizer exported", () => {
    expect(parseRulesetJson(JSON.stringify(BLIND_RULESET))).toEqual(BLIND_RULESET);
  });

  it("refuses text that is not a v2 ruleset, rather than crashing the board", () => {
    expect(parseRulesetJson("not json")).toBeNull();
    expect(parseRulesetJson("[]")).toBeNull();
    expect(parseRulesetJson(JSON.stringify({ version: 1, phases: [] }))).toBeNull();
    expect(parseRulesetJson(JSON.stringify({ version: 2 }))).toBeNull();
    // A phase with no id could never be addressed by a validation issue path.
    expect(parseRulesetJson(JSON.stringify({ version: 2, phases: [{ steps: [] }] }))).toBeNull();
  });
});

describe("validation mirrors what the editor itself owns", () => {
  it("accepts a generator phase, whose steps the server expands", () => {
    expect(validatePickBanDraft(draft())).toEqual([]);
  });

  it("reports a hand-authored phase with no steps, which would run nothing", () => {
    expect(validatePickBanDraft(draft({ kind: "hero", ruleset: emptyRuleset("hero") }))).toEqual([
      { key: "phaseWithoutSteps", values: { phase: "main" } },
    ]);
    expect(validatePickBanDraft(draft({ kind: "hero", ruleset: BLIND_RULESET }))).toEqual([]);
  });

  it("reports a ruleset with no phases at all", () => {
    const empty = { ...emptyRuleset("hero"), phases: [] };

    expect(validatePickBanDraft(draft({ ruleset: empty }))).toEqual([{ key: "noPhases" }]);
  });

  // A pool-less draft is a rules template, not a rejection: it is how the rules
  // of a whole tournament are authored once for narrower scopes to inherit.
  it("accepts an empty pool as a rules template", () => {
    expect(validatePickBanDraft(draft({ itemIds: [] }))).toEqual([]);
    expect(isRulesTemplate(draft({ itemIds: [] }))).toBe(true);
    expect(isRulesTemplate(draft())).toBe(false);
  });

  it("accepts groups with no candidates as a template, and reports a half-filled one", () => {
    expect(validatePickBanDraft(draft({ mode: "slots", slots: [] }))).toEqual([]);
    expect(
      validatePickBanDraft(
        draft({ mode: "slots", slots: [{ candidates: [], reserveItemId: null }] })
      )
    ).toEqual([]);
    expect(
      validatePickBanDraft(
        draft({
          mode: "slots",
          slots: [
            { candidates: [1, 2], reserveItemId: null },
            { candidates: [3], reserveItemId: null },
          ],
        })
      )
    ).toEqual([{ key: "slotTooFewCandidates", values: { slot: 2 } }]);
  });
});

describe("the cascade", () => {
  const tournamentWide = config({ id: 3, kind: "map", ruleset: BLIND_RULESET });

  it("prefills a narrower scope from the rules it inherits, and says so", () => {
    const moved = rescopePickBanDraft(emptyPickBanDraft("map"), 10, null, [tournamentWide]);

    expect(moved.ruleset).toEqual(BLIND_RULESET);
    expect(moved.inheritedFrom).toEqual({ stageId: null, round: null });
    expect(moved.configId).toBeNull();
  });

  it("never overwrites rules someone authored", () => {
    const authored = { ...emptyPickBanDraft("map"), ruleset: emptyRuleset("hero") };

    expect(rescopePickBanDraft(authored, 10, null, [tournamentWide]).ruleset).toEqual(
      authored.ruleset
    );
  });

  it("drops values carried over to a scope that inherits nothing", () => {
    const prefilled = rescopePickBanDraft(emptyPickBanDraft("hero"), 10, null, [tournamentWide]);

    expect(prefilled.inheritedFrom).toBeNull();
    expect(prefilled.ruleset).toEqual(emptyRuleset("hero"));
  });
});

describe("scope resolution", () => {
  const stages = [stage({ id: 10, max_rounds: 3, best_of: { default: 5, by_round: {}, final: null } })];

  it("takes a stage's rounds from the generated encounters when they exist", () => {
    const rounds = stageRoundOptions(10, [
      { stage_id: 10, round: 2, best_of: 3 },
      { stage_id: 10, round: 1, best_of: 3 },
      { stage_id: 11, round: 9, best_of: 3 },
      { stage_id: 10, round: 2, best_of: 3 },
    ]);

    expect(rounds).toEqual([1, 2]);
  });

  it("is empty before a bracket is generated -- the caller predicts instead of guessing here", () => {
    expect(stageRoundOptions(10, undefined)).toEqual([]);
    expect(stageRoundOptions(10, [])).toEqual([]);
  });

  it("prefers a generated encounter's series length over the stage default", () => {
    expect(resolveSeriesLength(10, 1, stages, [{ stage_id: 10, round: 1, best_of: 7 }])).toEqual({
      bestOf: 7,
      source: "round",
    });
  });

  it("labels a stage-wide or tournament-wide scope as a preview, not a promise", () => {
    expect(resolveSeriesLength(10, null, stages, undefined)).toEqual({
      bestOf: 5,
      source: "stage",
    });
    expect(resolveSeriesLength(null, null, stages, undefined).source).toBe("variesByMatch");
    expect(
      resolveSeriesLength(
        10,
        null,
        [stage({ id: 10, best_of: { default: 3, by_round: { "3": 5 }, final: null } })],
        undefined
      ).source
    ).toBe("variesByRound");
  });

  // 2026-09-05: a Bo5 grand final was previewed as Bo3, so its slot pool got
  // three map groups instead of five. `best_of.final` only outranks `default`
  // for the round that IS the final, and `round === max_rounds` cannot name it:
  // double elimination's grand final is `upperRounds + 1` off the team count,
  // while `max_rounds` is an independent planning field a new stage defaults
  // to 5. The bracket projection knows which round it is.
  it("gives a double elimination's grand final the length `final` sets", () => {
    const playoffs = stage({
      id: 10,
      stage_type: "double_elimination",
      // Four teams in the upper bracket: semifinal, final, then grand final as
      // round 3 -- two short of `max_rounds`.
      max_rounds: 5,
      items: [
        {
          id: 100,
          stage_id: 10,
          name: "Upper bracket",
          type: "bracket",
          order: 0,
          inputs: Array.from({ length: 4 }, (_, index) => ({
            id: 200 + index,
            stage_item_id: 100,
            slot: index + 1,
            input_type: "final",
            team_id: index + 1,
            source_stage_item_id: null,
            source_position: null,
          })),
        },
      ],
      best_of: { default: 3, by_round: {}, final: 5 },
    } as unknown as Partial<Stage>);

    expect(resolveSeriesLength(10, 3, [playoffs], [])).toEqual({ bestOf: 5, source: "round" });
    // The rounds before it keep the stage default, and so does the lower bracket.
    expect(resolveSeriesLength(10, 2, [playoffs], []).bestOf).toBe(3);
    expect(resolveSeriesLength(10, -1, [playoffs], []).bestOf).toBe(3);
    // The groups a round scope's slot pool needs follow it.
    expect(resolveSlotCount(10, 3, [playoffs], [])).toBe(5);
  });
});

// A slot pool is sized by the bracket, never by hand: the server plays the
// first `best_of` groups and keeps the room shut when there are fewer
// (`REASON_SLOT_COUNT_MISMATCH`), so a scope covering matches of different
// lengths needs the LONGEST one's count -- the preview length would leave the
// final unplayable.
describe("round groups are counted from the bracket", () => {
  it("takes a round scope's exact series length", () => {
    expect(resolveSlotCount(10, 1, [stage({ id: 10 })], [{ stage_id: 10, round: 1, best_of: 2 }])).toBe(
      2
    );
  });

  it("covers the longest match of a stage-wide or tournament-wide scope", () => {
    const encounters = [
      { stage_id: 10, round: 1, best_of: 3 },
      { stage_id: 10, round: 2, best_of: 5 },
      { stage_id: 11, round: 1, best_of: 7 },
    ];

    expect(resolveSlotCount(10, null, [stage({ id: 10 })], encounters)).toBe(5);
    expect(resolveSlotCount(null, null, [stage({ id: 10 })], encounters)).toBe(7);
  });

  it("reads the stage's configuration before the bracket exists, final included", () => {
    const stages = [stage({ id: 10, best_of: { default: 3, by_round: {}, final: 5 } })];

    expect(resolveSlotCount(10, null, stages, [])).toBe(5);
    expect(resolveSlotCount(10, null, stages, undefined)).toBe(5);
  });

  it("resizes a stored pool to that count, keeping the groups that survive", () => {
    const slots = [
      { candidates: [1, 2], reserveItemId: 9 },
      { candidates: [3, 4], reserveItemId: null },
    ];

    expect(alignSlots(slots, 2)).toBe(slots);
    expect(alignSlots(slots, 1)).toEqual([slots[0]]);
    expect(alignSlots(slots, 3)).toEqual([...slots, { candidates: [], reserveItemId: null }]);
  });
});

// A stage plays several rounds and a regulation routinely gives each its own
// maps. The store has no round dimension inside a config -- the scope key is
// `(stage, round)` -- so the stage screen holds every round at once and a save
// is one upsert per round.
describe("a stage's rounds each carry their own groups", () => {
  const slotConfig = (round: number | null, candidates: number[][]) =>
    config({
      id: round == null ? 1 : 100 + round,
      stage_id: 10,
      round,
      mode: "slots",
      item_ids: [],
      slots: candidates.map((group, index) => ({
        position: index + 1,
        reserve_item_id: null,
        candidates: group,
      })),
    });

  it("authors a round from its own config and the rest from what they inherit", () => {
    const sections = roundSlotsForStage({
      kind: "map",
      stageId: 10,
      rounds: [1, 2],
      configs: [slotConfig(2, [[7, 8], [8, 9]])],
      fallback: [{ candidates: [1, 2], reserveItemId: null }],
      slotCountFor: () => 2,
    });

    expect(sections[0].round).toBe(1);
    // Round 1 has no config: it starts from the stage's groups, padded to what
    // its bracket plays rather than left short.
    expect(sections[0].slots).toEqual([
      { candidates: [1, 2], reserveItemId: null },
      { candidates: [], reserveItemId: null },
    ]);
    expect(sections[1].slots.map((slot) => slot.candidates)).toEqual([
      [7, 8],
      [8, 9],
    ]);
  });

  it("fans one stage draft out into a config per round, scoped to it", () => {
    const stageDraft = draft({
      mode: "slots",
      stageId: 10,
      round: null,
      itemIds: [],
      roundSlots: [
        { round: 1, slots: [{ candidates: [1, 2], reserveItemId: null }] },
        { round: -1, slots: [{ candidates: [3, 4], reserveItemId: null }] },
      ],
    });

    const fanned = fanOutRoundDrafts(stageDraft);

    expect(fanned.map((one) => one.round)).toEqual([1, -1]);
    expect(fanned.map((one) => one.slots[0].candidates)).toEqual([
      [1, 2],
      [3, 4],
    ]);
    // Each one is a config of its own, and none of them carries the round
    // dimension any further.
    expect(fanned.every((one) => one.configId == null && one.roundSlots.length === 0)).toBe(true);
    expect(pickBanDraftToInput(fanned[1]).round).toBe(-1);
    // Same rules in every round: only the groups differ.
    expect(fanned.map((one) => one.ruleset)).toEqual([stageDraft.ruleset, stageDraft.ruleset]);
  });

  it("leaves a draft with no round dimension alone", () => {
    const single = draft({ mode: "slots", slots: [{ candidates: [1, 2], reserveItemId: null }] });

    expect(fanOutRoundDrafts(single)).toEqual([single]);
  });

  it("reports an underfilled group per round, since each round is saved on its own", () => {
    const stageDraft = draft({
      mode: "slots",
      stageId: 10,
      roundSlots: [
        { round: 1, slots: [{ candidates: [1, 2], reserveItemId: null }] },
        { round: 2, slots: [{ candidates: [1], reserveItemId: null }] },
      ],
    });

    expect(validatePickBanDraft(stageDraft)).toEqual([
      { key: "roundSlotTooFewCandidates", values: { round: 2, slot: 1 } },
    ]);
  });
});

describe("scope collisions", () => {
  const saved = [
    config({ id: 1, kind: "map", stage_id: null, round: null }),
    config({ id: 2, kind: "map", stage_id: 10, round: null }),
    config({ id: 3, kind: "hero", stage_id: null, round: null }),
  ];

  it("finds the config an upsert would silently replace", () => {
    expect(findScopeCollision(draft({ kind: "map", stageId: 10 }), saved)?.id).toBe(2);
    expect(findScopeCollision(draft({ kind: "hero" }), saved)?.id).toBe(3);
  });

  it("does not call a config a collision with itself, nor across kinds", () => {
    expect(findScopeCollision(draft({ configId: 2, kind: "map", stageId: 10 }), saved)).toBeNull();
    expect(findScopeCollision(draft({ kind: "map", stageId: 10, round: 1 }), saved)).toBeNull();
  });
});
