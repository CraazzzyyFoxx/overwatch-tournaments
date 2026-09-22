// The draft editor's whole safety argument is structural: bands partition the
// 45-rank ladder, so a gap or an overlap is unrepresentable rather than
// rejected by a validator. That claim is only worth anything if it is checked
// after EVERY action, including the ones that shrink and remove bands — so the
// suite drives a long mixed sequence and re-asserts the partition each step,
// instead of testing each action in isolation and hoping they compose.
//
// The second claim tested here is the coordinate bridge: the front-end edits
// ladder indices, the backend stores `rank_min`/`rank_max` plus
// `ow_rank_min`/`ow_rank_max`. A round-trip on a real version has to come back
// bit-identical, otherwise the editor silently re-bands every grid it opens.
import { describe, expect, it } from "vitest";

import { OW_REFERENCE_GRID } from "@/lib/divisions/grid";
import type { DivisionTier } from "@/types/workspace.types";
import {
  bandSize,
  bandsCoverLadder,
  bandsFromTiers,
  bandVerdict,
  describeAction,
  describeEdits,
  diffBands,
  draftReducer,
  initDraftState,
  LADDER,
  RANK_COUNT,
  tiersFromBands,
  type Action,
  type Band,
  type DraftState
} from "./draftReducer";

function band(partial: Partial<Band> & Pick<Band, "owFrom" | "owTo">): Band {
  return {
    slug: `band-${partial.owFrom}`,
    name: `Division ${partial.owFrom + 1}`,
    number: partial.owFrom + 1,
    icon_url: null,
    ...partial
  };
}

/** One band over the whole ladder — the state "Load standard OW ladder" is not. */
function singleBandDraft(): DraftState {
  const bands = [band({ owFrom: 0, owTo: RANK_COUNT - 1, slug: "all", name: "All ranks" })];
  return initDraftState(bands, bands);
}

/** Three bands, so `merge up`, `merge down` and both boundary edges all exist. */
function threeBandDraft(): DraftState {
  const bands = [
    band({ owFrom: 0, owTo: 2, slug: "champion", name: "Champion" }),
    band({ owFrom: 3, owTo: 20, slug: "elite", name: "Elite" }),
    band({ owFrom: 21, owTo: RANK_COUNT - 1, slug: "open", name: "Open" })
  ];
  return initDraftState(bands, bands);
}

function apply(state: DraftState, actions: Action[]): DraftState {
  return actions.reduce((current, action) => {
    const next = draftReducer(current, action);
    expect(
      bandsCoverLadder(next.bands),
      `partition broken by ${JSON.stringify(action)}: ${JSON.stringify(
        next.bands.map((entry) => [entry.owFrom, entry.owTo])
      )}`
    ).toBe(true);
    expect(next.bands.every((entry) => bandSize(entry) >= 1)).toBe(true);
    expect(next.bands.map((entry) => entry.number)).toEqual(
      next.bands.map((_, index) => index + 1)
    );
    return next;
  }, state);
}

describe("draftReducer invariants", () => {
  it("keeps the ladder partitioned through every kind of action", () => {
    const final = apply(threeBandDraft(), [
      { type: "splitAt", rank: 10 },
      { type: "splitAt", rank: 30 },
      { type: "splitWidest" },
      { type: "moveBoundary", bandIndex: 1, edge: "ceiling", delta: -1 },
      { type: "moveBoundary", bandIndex: 1, edge: "ceiling", delta: 1 },
      { type: "moveBoundary", bandIndex: 1, edge: "floor", delta: 1 },
      { type: "moveBoundary", bandIndex: 1, edge: "floor", delta: -1 },
      { type: "rename", bandIndex: 2, name: "Contender" },
      { type: "setIcon", bandIndex: 2, iconUrl: "https://cdn/contender.png" },
      { type: "merge", bandIndex: 2, into: "up" },
      { type: "merge", bandIndex: 1, into: "down" },
      { type: "undo" },
      { type: "undo" }
    ]);

    expect(final.bands.length).toBeGreaterThan(1);
  });

  it("never lets a boundary move empty its neighbour", () => {
    // Champion is a single rank: the boundary below it cannot rise any further.
    const state = initDraftState(
      [
        band({ owFrom: 0, owTo: 0, slug: "champion", name: "Champion" }),
        band({ owFrom: 1, owTo: RANK_COUNT - 1, slug: "rest", name: "Rest" })
      ],
      []
    );

    const blocked = draftReducer(state, {
      type: "moveBoundary",
      bandIndex: 1,
      edge: "ceiling",
      delta: -1
    });
    expect(blocked).toBe(state);
    expect(blocked.history).toHaveLength(0);

    // The other direction is legal and leaves Champion two ranks wide.
    const widened = apply(state, [
      { type: "moveBoundary", bandIndex: 1, edge: "ceiling", delta: 1 }
    ]);
    expect(widened.bands[0]).toMatchObject({ owFrom: 0, owTo: 1 });
    expect(widened.bands[1].owFrom).toBe(2);
  });

  it("refuses to split at a rank that is already a boundary, and outside the ladder", () => {
    const state = threeBandDraft();

    for (const rank of [0, 3, 21, -1, RANK_COUNT]) {
      expect(draftReducer(state, { type: "splitAt", rank })).toBe(state);
    }
  });

  it("splits so the upper half keeps the division and the lower half is the new one", () => {
    const state = apply(threeBandDraft(), [{ type: "splitAt", rank: 10 }]);

    expect(state.bands.map((entry) => [entry.owFrom, entry.owTo])).toEqual([
      [0, 2],
      [3, 9],
      [10, 20],
      [21, RANK_COUNT - 1]
    ]);
    expect(state.bands[1]).toMatchObject({ slug: "elite", name: "Elite" });
    // Borrows a crest until it is given one; that is what the badge reports.
    expect(state.bands[2]).toMatchObject({ name: "Untitled division", icon_url: null });
    expect(state.bands[2].id).toBeUndefined();
    expect(state.bands[2].slug).toBe(LADDER[10].slug);
  });

  it("splitWidest halves the widest band and stops when nothing can be split", () => {
    const wide = apply(threeBandDraft(), [{ type: "splitWidest" }]);
    // Open spans 21..44 (24 ranks), wider than Elite's 18 -> boundary at 21 + 12.
    expect(wide.bands.map((entry) => entry.owFrom)).toContain(33);

    // A fully split ladder has no band left with two ranks in it.
    const atomic = initDraftState(
      LADDER.map((tier, index) =>
        band({ owFrom: index, owTo: index, slug: tier.slug!, name: tier.name })
      ),
      []
    );
    expect(draftReducer(atomic, { type: "splitWidest" })).toBe(atomic);
  });

  it("merges a band into a neighbour that keeps its own identity", () => {
    const up = apply(threeBandDraft(), [{ type: "merge", bandIndex: 1, into: "up" }]);
    expect(up.bands).toHaveLength(2);
    expect(up.bands[0]).toMatchObject({ slug: "champion", owFrom: 0, owTo: 20 });

    const down = apply(threeBandDraft(), [{ type: "merge", bandIndex: 1, into: "down" }]);
    expect(down.bands).toHaveLength(2);
    expect(down.bands[1]).toMatchObject({ slug: "open", owFrom: 3, owTo: RANK_COUNT - 1 });

    // Nothing to merge into at the ends, and never below one band.
    const three = threeBandDraft();
    expect(draftReducer(three, { type: "merge", bandIndex: 0, into: "up" })).toBe(three);
    expect(draftReducer(three, { type: "merge", bandIndex: 2, into: "down" })).toBe(three);
    const one = singleBandDraft();
    expect(draftReducer(one, { type: "merge", bandIndex: 0, into: "up" })).toBe(one);
  });

  it("ignores a rename that is empty or unchanged", () => {
    const state = threeBandDraft();
    expect(draftReducer(state, { type: "rename", bandIndex: 0, name: "   " })).toBe(state);
    expect(draftReducer(state, { type: "rename", bandIndex: 0, name: "Champion" })).toBe(state);

    const renamed = apply(state, [{ type: "rename", bandIndex: 0, name: "  Apex  " }]);
    expect(renamed.bands[0].name).toBe("Apex");
  });

  it("undo walks the whole stack back and then stops", () => {
    const start = threeBandDraft();
    const edited = apply(start, [
      { type: "splitAt", rank: 10 },
      { type: "rename", bandIndex: 0, name: "Apex" }
    ]);
    expect(edited.history).toHaveLength(2);

    const back = apply(edited, [{ type: "undo" }, { type: "undo" }]);
    expect(back.bands).toEqual(start.bands);
    expect(back.history).toHaveLength(0);
    expect(draftReducer(back, { type: "undo" })).toBe(back);
  });
});

describe("tiers <-> bands round trip", () => {
  it("re-derives the reference ladder tier for tier, ow ranks included", () => {
    const bands = bandsFromTiers(OW_REFERENCE_GRID.tiers);

    expect(bands).toHaveLength(RANK_COUNT);
    expect(bandsCoverLadder(bands)).toBe(true);

    const tiers = tiersFromBands(bands);
    expect(tiers.map((tier) => tier.slug)).toEqual(LADDER.map((tier) => tier.slug));
    expect(tiers.map((tier) => tier.rank_min)).toEqual(LADDER.map((tier) => tier.rank_min));
    expect(tiers.map((tier) => tier.rank_max)).toEqual(LADDER.map((tier) => tier.rank_max));

    // The ladder's `rank_min` IS the tier's OW `rank_value`, so a one-rank band
    // pins both OW endpoints to it. A `null` endpoint would make the division
    // unreachable by OW rank (`resolve_division_from_ow_rank` skips it) — the
    // open-ended Champion 1 tier at the top is exactly where that used to bite.
    expect(tiers.every((tier) => tier.ow_rank_min === tier.rank_min)).toBe(true);
    expect(tiers.every((tier) => tier.ow_rank_max === tier.rank_min)).toBe(true);
    expect(tiers.every((tier) => tier.ow_rank_min !== null && tier.ow_rank_max !== null)).toBe(
      true
    );
    expect(tiers[0].rank_max).toBeNull();
  });

  it("round-trips a real multi-rank version and spans its OW range end to end", () => {
    // A stored version as the API returns one: ids, slugs, and bands several
    // ladder ranks wide.
    const stored: DivisionTier[] = [
      {
        id: 91,
        slug: "champion",
        number: 1,
        name: "Champion",
        rank_min: LADDER[2].rank_min,
        rank_max: null,
        sort_order: 0,
        icon_url: "https://cdn/champion.png"
      },
      {
        id: 92,
        slug: "elite",
        number: 2,
        name: "Elite",
        rank_min: LADDER[20].rank_min,
        rank_max: LADDER[3].rank_max,
        sort_order: 1,
        icon_url: "https://cdn/elite.png"
      },
      {
        id: 93,
        slug: "open",
        number: 3,
        name: "Open",
        rank_min: LADDER[RANK_COUNT - 1].rank_min,
        rank_max: LADDER[21].rank_max,
        sort_order: 2,
        icon_url: "https://cdn/open.png"
      }
    ];

    const bands = bandsFromTiers(stored);
    expect(bands.map((entry) => [entry.owFrom, entry.owTo])).toEqual([
      [0, 2],
      [3, 20],
      [21, RANK_COUNT - 1]
    ]);
    expect(bands.map((entry) => entry.id)).toEqual([91, 92, 93]);

    const tiers = tiersFromBands(bands);
    expect(tiers.map((tier) => tier.rank_min)).toEqual(stored.map((tier) => tier.rank_min));
    expect(tiers.map((tier) => tier.rank_max)).toEqual(stored.map((tier) => tier.rank_max));
    expect(tiers.map((tier) => tier.id)).toEqual([91, 92, 93]);
    // Every OW rank of the ladder falls inside exactly one band's OW range.
    expect(tiers[0].ow_rank_max).toBe(LADDER[0].rank_min);
    expect(tiers[2].ow_rank_min).toBe(LADDER[RANK_COUNT - 1].rank_min);
  });

  it("still yields a legal partition for a version that ignores ladder boundaries", () => {
    const ragged: DivisionTier[] = [
      { number: 1, name: "Top", rank_min: 3000, rank_max: null, icon_url: "x" },
      { number: 2, name: "Bottom", rank_min: 0, rank_max: 2999, icon_url: "y" }
    ];

    const bands = bandsFromTiers(ragged);
    expect(bandsCoverLadder(bands)).toBe(true);
    expect(bands.map((entry) => entry.name)).toEqual(["Top", "Bottom"]);
  });

  it("opens an empty version as one editable band instead of nothing", () => {
    expect(bandsFromTiers([])).toEqual([
      {
        slug: "division-1",
        name: "Division 1",
        number: 1,
        icon_url: null,
        owFrom: 0,
        owTo: RANK_COUNT - 1
      }
    ]);
  });
});

describe("diff against the parent version", () => {
  it("labels each band new, moved or renamed, structure before naming", () => {
    const base = threeBandDraft().bands;
    const state = apply(initDraftState(base, base), [
      { type: "rename", bandIndex: 0, name: "Apex" },
      { type: "splitAt", rank: 10 },
      { type: "moveBoundary", bandIndex: 3, edge: "ceiling", delta: -1 }
    ]);

    expect(bandVerdict(base, state.bands[0])).toBe("renamed");
    expect(bandVerdict(base, state.bands[1])).toBe("band moved");
    expect(bandVerdict(base, state.bands[2])).toBe("new");
    expect(bandVerdict(base, state.bands[3])).toBe("band moved");

    const diff = diffBands(base, state.bands);
    expect(diff.added.map((entry) => entry.name)).toEqual(["Untitled division"]);
    expect(diff.renamed.map((entry) => entry.after.name)).toEqual(["Apex"]);
    expect(diff.removed).toHaveLength(0);
  });

  it("reports a merged-away band as removed", () => {
    const base = threeBandDraft().bands;
    const merged = apply(initDraftState(base, base), [
      { type: "merge", bandIndex: 1, into: "up" }
    ]);

    expect(diffBands(base, merged.bands).removed.map((entry) => entry.slug)).toEqual(["elite"]);
  });
});

describe("edit log", () => {
  it("reads every kind of edit back as a sentence", () => {
    const base = threeBandDraft();
    const state = apply(base, [
      { type: "rename", bandIndex: 0, name: "Apex" },
      { type: "splitAt", rank: 10 },
      { type: "moveBoundary", bandIndex: 1, edge: "floor", delta: -1 },
      { type: "merge", bandIndex: 2, into: "up" }
    ]);

    expect(describeEdits(state)).toEqual([
      "Renamed Champion → Apex",
      `Split Elite at ${LADDER[10].name}`,
      `Untitled division now starts at ${LADDER[9].name} — Elite lost one rank`,
      "Merged Untitled division into Elite"
    ]);
  });

  it("names a crest change rather than falling back to a generic sentence", () => {
    const start = threeBandDraft();
    const iconed = apply(start, [
      { type: "setIcon", bandIndex: 1, iconUrl: "https://cdn/elite.png" }
    ]);

    expect(describeAction(start.bands, iconed.bands)).toBe("Set a crest for Elite");
  });
});
