// The bracket layout editor's draft, as the canvas and the PUT body see it.
//
// A template is a wiring diagram: every slot is a seed (`U3`), a winner, or a
// loser of another match, and each of those sources may sit in exactly one
// slot. The reducer is where that "exactly one" is enforced — connecting `W M1`
// somewhere new has to empty wherever it used to be, or the editor would offer
// a payload the server refuses with `result_reused`.
import { describe, expect, it } from "vitest";

import {
  draftFromTemplate,
  draftReducer,
  draftToBracketMatches,
  draftToTemplate,
  unusedSeeds,
  type Draft
} from "./templateDraft";

/** The 4-team single elimination the generator produces: two semis, one final. */
function seDraft(): Draft {
  return {
    upper_seeds: 4,
    lower_seeds: 0,
    matches: [
      { id: 1, round: 1, slots: [{ seed: "U1" }, { seed: "U4" }] },
      { id: 2, round: 1, slots: [{ seed: "U2" }, { seed: "U3" }] },
      {
        id: 3,
        round: 2,
        slots: [
          { source_match: 1, source_position: 1 },
          { source_match: 2, source_position: 1 }
        ]
      }
    ]
  };
}

const matchOf = (draft: Draft, id: number) => draft.matches.find((match) => match.id === id)!;

describe("draftReducer · connect", () => {
  it("writes the winner into the target slot", () => {
    const draft = draftReducer(
      { ...seDraft(), matches: [...seDraft().matches, { id: 4, round: 3, slots: [null, null] }] },
      { type: "connect", source: 3, role: "winner", target: 4, slot: 1 }
    );

    expect(matchOf(draft, 4).slots[0]).toEqual({ source_match: 3, source_position: 1 });
  });

  it("empties the slot the same result used to sit in — a result advances once", () => {
    const draft = draftReducer(seDraft(), {
      type: "connect",
      source: 1,
      role: "winner",
      target: 3,
      slot: 2
    });

    expect(matchOf(draft, 3).slots[1]).toEqual({ source_match: 1, source_position: 1 });
    // `W M1` was the final's home slot; it cannot be in both.
    expect(matchOf(draft, 3).slots[0]).toBeNull();
  });

  it("writes a loser drop as `loser_of`, which is a different source from the winner", () => {
    const start = {
      ...seDraft(),
      matches: [...seDraft().matches, { id: 4, round: -1, slots: [null, null] }]
    };
    const draft = draftReducer(start, {
      type: "connect",
      source: 1,
      role: "loser",
      target: 4,
      slot: 1
    });

    expect(matchOf(draft, 4).slots[0]).toEqual({ source_match: 1, source_position: 2 });
    // The winner of M1 keeps its own slot: (M1, winner) and (M1, loser) are two pairs.
    expect(matchOf(draft, 3).slots[0]).toEqual({ source_match: 1, source_position: 1 });
  });
});

describe("draftReducer · seeds", () => {
  it("places a seed", () => {
    const draft = draftReducer(
      {
        ...seDraft(),
        lower_seeds: 2,
        matches: [...seDraft().matches, { id: 4, round: -1, slots: [null, null] }]
      },
      { type: "seed", target: 4, slot: 1, seed: "L1" }
    );

    expect(matchOf(draft, 4).slots[0]).toEqual({ seed: "L1" });
  });

  it("moves a seed that is already placed instead of cloning the team", () => {
    const draft = draftReducer(seDraft(), { type: "seed", target: 2, slot: 1, seed: "U1" });

    expect(matchOf(draft, 2).slots[0]).toEqual({ seed: "U1" });
    expect(matchOf(draft, 1).slots[0]).toBeNull();
  });

  it("clears a slot", () => {
    const draft = draftReducer(seDraft(), { type: "clear", target: 1, slot: 2 });

    expect(matchOf(draft, 1).slots[1]).toBeNull();
  });

  it("swaps two seeds across matches of one round", () => {
    const draft = draftReducer(seDraft(), {
      type: "swap",
      a: { match: 1, slot: 2 },
      b: { match: 2, slot: 1 }
    });

    expect(matchOf(draft, 1).slots).toEqual([{ seed: "U1" }, { seed: "U2" }]);
    expect(matchOf(draft, 2).slots).toEqual([{ seed: "U4" }, { seed: "U3" }]);
  });

  it("moves a seed into an empty slot of the round, leaving its own empty", () => {
    const start = draftReducer(seDraft(), { type: "clear", target: 2, slot: 2 });
    const draft = draftReducer(start, {
      type: "swap",
      a: { match: 1, slot: 1 },
      b: { match: 2, slot: 2 }
    });

    expect(matchOf(draft, 1).slots[0]).toBeNull();
    expect(matchOf(draft, 2).slots[1]).toEqual({ seed: "U1" });
  });

  it("refuses a swap across rounds", () => {
    const start = seDraft();

    expect(
      draftReducer(start, { type: "swap", a: { match: 1, slot: 1 }, b: { match: 3, slot: 1 } })
    ).toBe(start);
  });
});

describe("draftReducer · matches", () => {
  it("appends an empty match with the next free id", () => {
    const draft = draftReducer(seDraft(), { type: "addMatch", round: 1 });

    expect(draft.matches.at(-1)).toEqual({ id: 4, round: 1, slots: [null, null] });
  });

  it("inserts a new upper round BEFORE the final, pushing the final one round out", () => {
    // `+ round` on the upper section cannot append past the final: the final is
    // by definition the only match of the last positive round.
    const draft = draftReducer(seDraft(), { type: "addMatch", round: 2, beforeFinal: true });

    expect(matchOf(draft, 3).round).toBe(3);
    expect(draft.matches.at(-1)).toEqual({ id: 4, round: 2, slots: [null, null] });
  });

  it("deletes a match and empties every slot that pointed at it", () => {
    const draft = draftReducer(seDraft(), { type: "deleteMatch", id: 1 });

    expect(draft.matches.map((match) => match.id)).toEqual([2, 3]);
    expect(matchOf(draft, 3).slots[0]).toBeNull();
    expect(matchOf(draft, 3).slots[1]).toEqual({ source_match: 2, source_position: 1 });
  });

  it("moves a match past its neighbour in the same round, and nowhere else", () => {
    // List order is display order within a round (spec §5.1), so a swap across
    // rounds would reorder nothing a viewer can see.
    const up = draftReducer(seDraft(), { type: "move", id: 2, direction: -1 });
    expect(up.matches.map((match) => match.id)).toEqual([2, 1, 3]);

    const alone = draftReducer(seDraft(), { type: "move", id: 3, direction: -1 });
    expect(alone.matches.map((match) => match.id)).toEqual([1, 2, 3]);
  });

  it("sets the seed counts", () => {
    const draft = draftReducer(seDraft(), { type: "setSeeds", upper: 4, lower: 4 });

    expect([draft.upper_seeds, draft.lower_seeds]).toEqual([4, 4]);
  });
});

describe("draftReducer · bounds", () => {
  // The server's model rejects anything past these, so the editor never offers it.
  it("does not add a match past the id or round bound", () => {
    const maxId = {
      ...seDraft(),
      matches: [...seDraft().matches, { id: 10_000, round: 1, slots: [null, null] }]
    };
    expect(draftReducer(maxId, { type: "addMatch", round: 1 })).toBe(maxId);

    const deep = seDraft();
    expect(draftReducer(deep, { type: "addMatch", round: -257 })).toBe(deep);
  });

  it("does not push the final past the round bound", () => {
    const atBound = {
      ...seDraft(),
      matches: seDraft().matches.map((match) => ({ ...match, round: 256 }))
    };

    expect(draftReducer(atBound, { type: "addMatch", round: 256, beforeFinal: true })).toBe(
      atBound
    );
  });

  it("clamps the seed counts", () => {
    const high = draftReducer(seDraft(), { type: "setSeeds", upper: 513, lower: 9999 });
    expect([high.upper_seeds, high.lower_seeds]).toEqual([512, 512]);

    const low = draftReducer(seDraft(), { type: "setSeeds", upper: 0, lower: -3 });
    expect([low.upper_seeds, low.lower_seeds]).toEqual([2, 0]);
  });
});

describe("draftToTemplate", () => {
  it("refuses a draft with an unwired slot — the payload cannot express it", () => {
    const draft = draftReducer(seDraft(), { type: "clear", target: 3, slot: 1 });

    expect(draftToTemplate(draft)).toBeNull();
  });

  it("round-trips a complete draft", () => {
    const template = draftToTemplate(seDraft());

    expect(template).toEqual({
      version: 1,
      upper_seeds: 4,
      lower_seeds: 0,
      matches: [
        {
          id: 1,
          round: 1,
          slots: [
            { slot: 1, seed: "U1" },
            { slot: 2, seed: "U4" }
          ]
        },
        {
          id: 2,
          round: 1,
          slots: [
            { slot: 1, seed: "U2" },
            { slot: 2, seed: "U3" }
          ]
        },
        {
          id: 3,
          round: 2,
          slots: [
            { slot: 1, source_match: 1, source_position: 1 },
            { slot: 2, source_match: 2, source_position: 1 }
          ]
        }
      ]
    });
    expect(draftFromTemplate(template!)).toEqual(seDraft());
  });
});

describe("draftToBracketMatches", () => {
  it("names seed slots and leaves wired ones to the view's own hints", () => {
    const matches = draftToBracketMatches(seDraft());

    expect(matches[0]).toMatchObject({
      id: 1,
      round: 1,
      teams: [
        { slot: 1, team_id: null, name: "U1" },
        { slot: 2, team_id: null, name: "U4" }
      ],
      sources: []
    });
    // A wired slot stays TBD (no seat): `computeSlotHints` turns its source into "W M1".
    expect(matches[2].teams).toEqual([]);
    expect(matches[2].sources).toEqual([
      { encounter_id: 1, source_position: 1, slot: 1 },
      { encounter_id: 2, source_position: 1, slot: 2 }
    ]);
  });

  it("draws an unwired slot as TBD with no source", () => {
    const matches = draftToBracketMatches(
      draftReducer(seDraft(), { type: "clear", target: 3, slot: 2 })
    );

    expect(matches[2].teams).toEqual([]);
    expect(matches[2].sources).toEqual([{ encounter_id: 1, source_position: 1, slot: 1 }]);
  });
});

describe("unusedSeeds", () => {
  it("lists every seed the stage has that no slot holds", () => {
    const draft = { ...seDraft(), lower_seeds: 2 };

    expect(unusedSeeds(draft)).toEqual(["L1", "L2"]);
    expect(unusedSeeds(draftReducer(draft, { type: "clear", target: 1, slot: 1 }))).toEqual([
      "U1",
      "L1",
      "L2"
    ]);
  });

  it("offers a match only the seeds of its own half", () => {
    // The validator refuses `L1` in an upper-round match and `U1` in a lower
    // one, so a menu offering both offers a draft that cannot be saved.
    const draft = draftReducer(
      { ...seDraft(), lower_seeds: 2 },
      {
        type: "clear",
        target: 1,
        slot: 1
      }
    );

    expect(unusedSeeds(draft, 1)).toEqual(["U1"]);
    expect(unusedSeeds(draft, -1)).toEqual(["L1", "L2"]);
  });
});
