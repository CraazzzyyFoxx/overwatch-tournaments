// A division has two coordinates — its range on the workspace's rank scale and
// the OW ranks that land in it — and the editor's safety argument is that each
// scale keeps its invariant by construction:
//  - ladder: the bands partition all 45 ranks and every floor is the ladder's;
//  - custom: floors strictly descend and OW runs stay ordered and disjoint.
// Both are re-asserted after EVERY action of a long mixed sequence, instead of
// testing each action alone and hoping they compose.
//
// The second claim is the bridge to stored tiers: a version has to come back
// bit-identical, and a grid on its own scale ("New Era x5", twenty divisions of
// 100) must open as itself. Reading it through the OW ladder is what used to
// drop four divisions and rewrite every range on save.
import { describe, expect, it } from "vitest";

import { OW_REFERENCE_GRID } from "@/lib/divisions/grid";
import type { DivisionTier } from "@/types/workspace.types";
import {
  bandsCoverLadder,
  bandsFromTiers,
  bandVerdict,
  describeEdits,
  diffBands,
  draftReducer,
  floorError,
  floorsDescend,
  initDraftState,
  LADDER,
  ladderOwners,
  RANK_COUNT,
  scaleOf,
  tiersFromBands,
  type Action,
  type Band,
  type DraftState
} from "./draftReducer";

const LAST = RANK_COUNT - 1;

function ladderBand(slug: string, name: string, from: number, to: number): Band {
  return {
    slug,
    name,
    number: 0,
    icon_url: null,
    rankMin: LADDER[to].rank_min,
    rankMax: null,
    ow: { from, to }
  };
}

/** Three ladder bands, so `merge up`, `merge down` and both boundary directions all exist. */
function threeBandDraft(): DraftState {
  const bands = [
    ladderBand("champion", "Champion", 0, 2),
    ladderBand("elite", "Elite", 3, 20),
    ladderBand("open", "Open", 21, LAST)
  ];
  return initDraftState(bands, "ladder", initDraftState(bands, "ladder", []).bands);
}

/** "New Era x5" as the API returns it: twenty divisions of 100 on 100 … 2099, no OW links. */
const NEW_ERA: DivisionTier[] = Array.from({ length: 20 }, (_, index) => {
  const number = index + 1;
  const rankMin = 2100 - 100 * number;
  return {
    id: 700 + number,
    slug: `division-${number}`,
    number,
    name: `Division ${number}`,
    rank_min: rankMin,
    rank_max: number === 1 ? null : rankMin + 99,
    sort_order: index,
    icon_url: `https://cdn/division-${number}.png`
  };
});

function newEraDraft(): DraftState {
  const bands = bandsFromTiers(NEW_ERA);
  return initDraftState(bands, scaleOf(NEW_ERA), bands);
}

function expectDerived(bands: Band[], why: string) {
  expect(
    bands.map((band) => band.number),
    why
  ).toEqual(bands.map((_, index) => index + 1));
  expect(
    bands.map((band) => band.rankMax),
    why
  ).toEqual(bands.map((_, index) => (index === 0 ? null : bands[index - 1].rankMin - 1)));
}

function expectLadderInvariant(bands: Band[], why: string) {
  expect(bandsCoverLadder(bands), why).toBe(true);
  for (const band of bands) {
    if (band.ow!.to !== LAST) expect(band.rankMin, why).toBe(LADDER[band.ow!.to].rank_min);
  }
  expectDerived(bands, why);
}

function expectCustomInvariant(bands: Band[], why: string) {
  expect(floorsDescend(bands), why).toBe(true);
  const owners = ladderOwners(bands);
  // Walking down the ladder never climbs back to a higher division…
  const linked = owners.filter((owner): owner is number => owner !== null);
  expect(linked, why).toEqual([...linked].sort((left, right) => left - right));
  // …and no run was overwritten by a neighbour's, i.e. no two runs overlap.
  bands.forEach((band, index) => {
    if (!band.ow) return;
    for (let rank = band.ow.from; rank <= band.ow.to; rank += 1) {
      expect(owners[rank], why).toBe(index);
    }
  });
  expectDerived(bands, why);
}

function apply(state: DraftState, actions: Action[]): DraftState {
  return actions.reduce((current, action) => {
    const next = draftReducer(current, action);
    const why = `after ${JSON.stringify(action)}`;
    if (next.scale === "ladder") expectLadderInvariant(next.bands, why);
    else expectCustomInvariant(next.bands, why);
    return next;
  }, state);
}

describe("ladder scale", () => {
  it("keeps the ladder partitioned through every kind of action", () => {
    const final = apply(threeBandDraft(), [
      { type: "splitAt", rank: 10 },
      { type: "splitAt", rank: 30 },
      { type: "split", bandIndex: 4 },
      { type: "nudge", rank: 10, delta: -1 },
      { type: "nudge", rank: 9, delta: 1 },
      { type: "nudge", rank: 21, delta: 1 },
      { type: "rename", bandIndex: 2, name: "Contender" },
      { type: "setIcon", bandIndex: 2, iconUrl: "https://cdn/contender.png" },
      { type: "merge", bandIndex: 2, into: "up" },
      { type: "merge", bandIndex: 1, into: "down" },
      { type: "undo" },
      { type: "undo" }
    ]);

    expect(final.bands.length).toBeGreaterThan(1);
  });

  it("never lets a nudge empty a band, and a one-rank band can always join", () => {
    // The reported dead end: 45 one-rank divisions, where no boundary can move.
    const atomic = initDraftState(
      LADDER.map((tier, index) => ladderBand(tier.slug!, tier.name, index, index)),
      "ladder",
      []
    );
    for (const rank of [1, 20, LAST]) {
      expect(draftReducer(atomic, { type: "nudge", rank, delta: -1 })).toBe(atomic);
      expect(draftReducer(atomic, { type: "nudge", rank, delta: 1 })).toBe(atomic);
    }

    // Joining frees the boundary: Champion 1–2 can now hand a rank down.
    const joined = apply(atomic, [{ type: "merge", bandIndex: 1, into: "up" }]);
    expect(joined.bands[0]).toMatchObject({ slug: "champion-1", ow: { from: 0, to: 1 } });
    const moved = apply(joined, [{ type: "nudge", rank: 2, delta: -1 }]);
    expect(moved.bands[0].ow).toEqual({ from: 0, to: 0 });
    expect(moved.bands[1].ow).toEqual({ from: 1, to: 2 });
  });

  it("refuses to split at a rank that is already a boundary, and outside the ladder", () => {
    const state = threeBandDraft();
    for (const rank of [0, 3, 21, -1, RANK_COUNT]) {
      expect(draftReducer(state, { type: "splitAt", rank })).toBe(state);
    }
  });

  it("splits so the upper half keeps the division and the lower half is the new one", () => {
    const state = apply(threeBandDraft(), [{ type: "splitAt", rank: 10 }]);

    expect(state.bands.map((band) => band.ow)).toEqual([
      { from: 0, to: 2 },
      { from: 3, to: 9 },
      { from: 10, to: 20 },
      { from: 21, to: LAST }
    ]);
    expect(state.bands[1]).toMatchObject({ slug: "elite", name: "Elite" });
    expect(state.bands[2]).toMatchObject({
      name: "Untitled division",
      icon_url: null,
      slug: LADDER[10].slug
    });
    expect(state.bands[2].id).toBeUndefined();
  });

  it("merges a band into a neighbour that keeps its own identity", () => {
    const up = apply(threeBandDraft(), [{ type: "merge", bandIndex: 1, into: "up" }]);
    expect(up.bands[0]).toMatchObject({ slug: "champion", ow: { from: 0, to: 20 } });

    const down = apply(threeBandDraft(), [{ type: "merge", bandIndex: 1, into: "down" }]);
    expect(down.bands[1]).toMatchObject({ slug: "open", ow: { from: 3, to: LAST } });

    const three = threeBandDraft();
    expect(draftReducer(three, { type: "merge", bandIndex: 0, into: "up" })).toBe(three);
    expect(draftReducer(three, { type: "merge", bandIndex: 2, into: "down" })).toBe(three);
  });

  it("keeps a bottom floor below the ladder through edits", () => {
    // `0 … 3999` is a ladder band: every rank under Bronze 5 lands at the bottom anyway.
    const tiers: DivisionTier[] = [
      { id: 1, slug: "top", number: 1, name: "Top", rank_min: 4000, rank_max: null, icon_url: "/a.png" },
      { id: 2, slug: "open", number: 2, name: "Open", rank_min: 0, rank_max: 3999, icon_url: "/b.png" }
    ];
    expect(scaleOf(tiers)).toBe("ladder");

    const split = apply(initDraftState(bandsFromTiers(tiers), "ladder", []), [
      { type: "splitAt", rank: 30 }
    ]);
    expect(split.bands.at(-1)!.rankMin).toBe(0);
    expect(split.bands[1].rankMin).toBe(LADDER[29].rank_min);
  });

  it("refuses the custom-scale edits that would break the partition", () => {
    const state = threeBandDraft();
    expect(draftReducer(state, { type: "setFloor", bandIndex: 1, rankMin: 3000 })).toBe(state);
    expect(draftReducer(state, { type: "link", bandIndex: 1, from: 0, to: 5 })).toBe(state);
    expect(draftReducer(state, { type: "unlink", bandIndex: 1 })).toBe(state);
  });

  it("ignores a rename that is empty or unchanged", () => {
    const state = threeBandDraft();
    expect(draftReducer(state, { type: "rename", bandIndex: 0, name: "   " })).toBe(state);
    expect(draftReducer(state, { type: "rename", bandIndex: 0, name: "Champion" })).toBe(state);
    expect(apply(state, [{ type: "rename", bandIndex: 0, name: "  Apex  " }]).bands[0].name).toBe(
      "Apex"
    );
  });

  it("undo walks the whole stack back, scale included, and then stops", () => {
    const start = threeBandDraft();
    const edited = apply(start, [
      { type: "splitAt", rank: 10 },
      { type: "setScale", scale: "custom" },
      { type: "setFloor", bandIndex: 1, rankMin: 3500 }
    ]);
    expect(edited.scale).toBe("custom");

    const back = apply(edited, [{ type: "undo" }, { type: "undo" }, { type: "undo" }]);
    expect(back.bands).toEqual(start.bands);
    expect(back.scale).toBe("ladder");
    expect(draftReducer(back, { type: "undo" })).toBe(back);
  });
});

describe("custom scale", () => {
  it("keeps floors descending and OW runs ordered through every kind of action", () => {
    const final = apply(newEraDraft(), [
      { type: "link", bandIndex: 0, from: 0, to: 2 },
      { type: "link", bandIndex: 1, from: 3, to: 5 },
      { type: "nudge", rank: 3, delta: 1 },
      { type: "nudge", rank: 4, delta: -1 },
      { type: "nudge", rank: 6, delta: 1 },
      { type: "nudge", rank: 7, delta: -1 },
      { type: "link", bandIndex: 19, from: 40, to: LAST },
      { type: "setFloor", bandIndex: 4, rankMin: 1650 },
      { type: "split", bandIndex: 0 },
      { type: "split", bandIndex: 6 },
      { type: "unlink", bandIndex: 2 },
      { type: "merge", bandIndex: 18, into: "down" },
      { type: "merge", bandIndex: 3, into: "up" },
      { type: "undo" }
    ]);

    expect(final.scale).toBe("custom");
  });

  it("refuses a floor that would overlap a neighbour, and says why", () => {
    const state = newEraDraft();
    // Division 5 sits between Division 4 (1700) and Division 6 (1500).
    expect(floorError(state.bands, 4, "1650")).toBeNull();
    expect(floorError(state.bands, 4, "1700")).toBe("Must be below Division 4 (1700).");
    expect(floorError(state.bands, 4, "1500")).toBe("Must be above Division 6 (1500).");
    expect(floorError(state.bands, 4, "16.5")).toBe("Enter a whole number.");
    expect(draftReducer(state, { type: "setFloor", bandIndex: 4, rankMin: 1700 })).toBe(state);

    const moved = apply(state, [{ type: "setFloor", bandIndex: 4, rankMin: 1650 }]);
    expect(moved.bands[4]).toMatchObject({ rankMin: 1650, rankMax: 1699 });
    expect(moved.bands[5].rankMax).toBe(1649);
  });

  it("links a run by taking ranks from the neighbours, which may leave some unlinked", () => {
    const state = apply(newEraDraft(), [
      { type: "link", bandIndex: 0, from: 2, to: 0 },
      { type: "link", bandIndex: 1, from: 3, to: 5 }
    ]);

    expect(state.bands[0].ow).toEqual({ from: 0, to: 2 });
    expect(state.bands[1].ow).toEqual({ from: 3, to: 5 });
    // Division 1 used to hold Champion 1 … Platinum 5 and Division 2 Gold 1:
    // what the links released lands nowhere until it is linked again.
    const owners = ladderOwners(state.bands);
    expect(owners.slice(6, 31).every((owner) => owner === null)).toBe(true);
    expect(owners[31]).toBe(2);
  });

  it("lets a boundary move unlink a division's last rank, and fill a gap", () => {
    // Division 16 holds only Bronze 5; handing it up leaves Division 16 unlinked.
    const state = apply(newEraDraft(), [{ type: "nudge", rank: LAST, delta: 1 }]);
    expect(state.bands[15].ow).toBeNull();
    expect(state.bands[14].ow).toEqual({ from: LAST - 1, to: LAST });

    const gap = apply(newEraDraft(), [
      { type: "link", bandIndex: 1, from: 3, to: 5 },
      { type: "nudge", rank: 6, delta: 1 }
    ]);
    expect(gap.bands[1].ow).toEqual({ from: 3, to: 6 });
  });

  it("halves a native range, the open-ended top by one width of the division below", () => {
    const state = apply(newEraDraft(), [
      { type: "split", bandIndex: 4 },
      { type: "split", bandIndex: 0 }
    ]);

    // Division 5 (1600–1699, one OW rank): the new lower half has no rank to share.
    expect(state.bands[5]).toMatchObject({ name: "Division 5", rankMin: 1650, rankMax: 1699 });
    expect(state.bands[6]).toMatchObject({
      name: "Untitled division",
      slug: "division-1600",
      rankMin: 1600,
      rankMax: 1649,
      ow: null
    });
    // Division 1 (2000+, thirty OW ranks) gives 2000–2099 and the lower fifteen ranks away.
    expect(state.bands[0]).toMatchObject({ rankMin: 2100, rankMax: null, ow: { from: 0, to: 14 } });
    expect(state.bands[1]).toMatchObject({ rankMin: 2000, rankMax: 2099, ow: { from: 15, to: 29 } });
  });

  it("merges into a neighbour that takes the lower floor and both runs", () => {
    const state = apply(newEraDraft(), [{ type: "merge", bandIndex: 16, into: "up" }]);
    expect(state.bands[15]).toMatchObject({
      slug: "division-16",
      rankMin: 400,
      rankMax: 599,
      ow: { from: LAST, to: LAST }
    });
    expect(state.bands[16].rankMax).toBe(399);
  });

  it("follows the ladder only once every rank and division is linked, then rewrites floors", () => {
    const newEra = newEraDraft();
    expect(newEra.scale).toBe("custom");
    expect(draftReducer(newEra, { type: "setScale", scale: "ladder" })).toBe(newEra);

    const custom = apply(threeBandDraft(), [
      { type: "setScale", scale: "custom" },
      { type: "setFloor", bandIndex: 1, rankMin: 3000 }
    ]);
    expect(custom.bands[1].rankMin).toBe(3000);
    const ladder = apply(custom, [{ type: "setScale", scale: "ladder" }]);
    expect(ladder.bands[1].rankMin).toBe(LADDER[20].rank_min);
  });
});

describe("tiers <-> bands", () => {
  it("re-derives the reference ladder tier for tier, OW ranks included", () => {
    const bands = bandsFromTiers(OW_REFERENCE_GRID.tiers);
    expect(scaleOf(OW_REFERENCE_GRID.tiers)).toBe("ladder");
    expect(bandsCoverLadder(bands)).toBe(true);

    const tiers = tiersFromBands(bands);
    expect(tiers.map((tier) => tier.slug)).toEqual(LADDER.map((tier) => tier.slug));
    expect(tiers.map((tier) => tier.rank_min)).toEqual(LADDER.map((tier) => tier.rank_min));
    expect(tiers.map((tier) => tier.rank_max)).toEqual(LADDER.map((tier) => tier.rank_max));
    // A ladder rank's `rank_min` IS its OW rank value, so a one-rank band pins both
    // OW endpoints to it — a `null` endpoint would make the division unreachable.
    expect(tiers.every((tier) => tier.ow_rank_min === tier.rank_min)).toBe(true);
    expect(tiers.every((tier) => tier.ow_rank_max === tier.rank_min)).toBe(true);
  });

  it("opens a grid on its own scale as itself, with the backend's OW fallback drawn", () => {
    expect(scaleOf(NEW_ERA)).toBe("custom");
    const bands = bandsFromTiers(NEW_ERA);

    expect(bands.map((band) => band.id)).toEqual(NEW_ERA.map((tier) => tier.id));
    // No stored link: an OW rank resolves by rank range, bottom division as fallback.
    expect(bands[0].ow).toEqual({ from: 0, to: 29 });
    expect(bands[1].ow).toEqual({ from: 30, to: 30 });
    expect(bands[15].ow).toEqual({ from: LAST, to: LAST });
    expect(bands.slice(16).every((band) => band.ow === null)).toBe(true);

    const tiers = tiersFromBands(bands);
    expect(tiers.map((tier) => [tier.rank_min, tier.rank_max])).toEqual(
      NEW_ERA.map((tier) => [tier.rank_min, tier.rank_max])
    );
    expect(tiers.map((tier) => tier.icon_url)).toEqual(NEW_ERA.map((tier) => tier.icon_url));
  });

  it("round-trips explicit OW links bit-identically", () => {
    const stored: DivisionTier[] = [
      { id: 1, slug: "d1", number: 1, name: "Division 1", rank_min: 2000, rank_max: null, icon_url: "/1.png", ow_rank_min: 4700, ow_rank_max: 4900 },
      { id: 2, slug: "d2", number: 2, name: "Division 2", rank_min: 1900, rank_max: 1999, icon_url: "/2.png", ow_rank_min: 4000, ow_rank_max: 4600 },
      { id: 3, slug: "d3", number: 3, name: "Division 3", rank_min: 0, rank_max: 1899, icon_url: "/3.png", ow_rank_min: 500, ow_rank_max: 3900 }
    ];
    expect(scaleOf(stored)).toBe("custom");

    const tiers = tiersFromBands(bandsFromTiers(stored));
    for (const key of ["id", "slug", "rank_min", "rank_max", "icon_url", "ow_rank_min", "ow_rank_max"] as const) {
      expect(tiers.map((tier) => tier[key])).toEqual(stored.map((tier) => tier[key]));
    }
  });

  it("reads inverted and overlapping OW pairs the way the backend resolves them", () => {
    // Mirrors backend `_grid_with_inverted_top`: pairs entered high → low, sharing Champion 3.
    const stored: DivisionTier[] = [
      { id: 1, number: 1, name: "Division 1", rank_min: 2000, rank_max: 2099, icon_url: "/1.png", ow_rank_min: 4900, ow_rank_max: 4700 },
      { id: 2, number: 2, name: "Division 2", rank_min: 1900, rank_max: 1999, icon_url: "/2.png", ow_rank_min: 4700, ow_rank_max: 4500 },
      { id: 14, number: 14, name: "Division 14", rank_min: 700, rank_max: 799, icon_url: "/14.png", ow_rank_min: 3200, ow_rank_max: 3300 }
    ];
    const bands = bandsFromTiers(stored);

    // First match wins, so Champion 3 stays in Division 1.
    expect(bands.map((band) => band.ow)).toEqual([
      { from: 0, to: 2 },
      { from: 3, to: 4 },
      { from: 16, to: 17 }
    ]);
    expect(ladderOwners(bands).filter((owner) => owner === null)).toHaveLength(RANK_COUNT - 7);
  });

  it("opens an empty version as one editable division instead of nothing", () => {
    expect(bandsFromTiers([])).toEqual([
      {
        slug: "division-1",
        name: "Division 1",
        number: 1,
        icon_url: null,
        rankMin: LADDER[LAST].rank_min,
        rankMax: null,
        ow: { from: 0, to: LAST }
      }
    ]);
  });
});

describe("diff against the parent version", () => {
  it("labels each band new, range moved, relinked or renamed — range before link before name", () => {
    const ladder = threeBandDraft();
    const state = apply(ladder, [
      { type: "rename", bandIndex: 0, name: "Apex" },
      { type: "splitAt", rank: 10 },
      { type: "nudge", rank: 21, delta: -1 }
    ]);
    expect(bandVerdict(ladder.base, state.bands[0])).toBe("renamed");
    expect(bandVerdict(ladder.base, state.bands[1])).toBe("range moved");
    expect(bandVerdict(ladder.base, state.bands[2])).toBe("new");
    expect(bandVerdict(ladder.base, state.bands[3])).toBe("range moved");

    const newEra = newEraDraft();
    const linked = apply(newEra, [{ type: "link", bandIndex: 1, from: 3, to: 5 }]);
    expect(bandVerdict(newEra.base, linked.bands[1])).toBe("relinked");
    expect(bandVerdict(newEra.base, linked.bands[2])).toBeNull();

    const diff = diffBands(ladder.base, state.bands);
    expect(diff.added.map((band) => band.name)).toEqual(["Untitled division"]);
    expect(diff.renamed.map((entry) => entry.after.name)).toEqual(["Apex"]);
  });

  it("reports a merged-away band as removed", () => {
    const state = threeBandDraft();
    const merged = apply(state, [{ type: "merge", bandIndex: 1, into: "up" }]);
    expect(diffBands(state.base, merged.bands).removed.map((band) => band.slug)).toEqual([
      "elite"
    ]);
  });
});

describe("edit log", () => {
  it("reads every kind of edit back as a sentence", () => {
    const ladder = apply(threeBandDraft(), [
      { type: "rename", bandIndex: 0, name: "Apex" },
      { type: "splitAt", rank: 10 },
      { type: "nudge", rank: 10, delta: -1 },
      { type: "merge", bandIndex: 2, into: "up" },
      { type: "setIcon", bandIndex: 1, iconUrl: "https://cdn/elite.png" },
      { type: "setScale", scale: "custom" }
    ]);
    expect(describeEdits(ladder)).toEqual([
      "Renamed Champion → Apex",
      `Split Elite at ${LADDER[10].name}`,
      `${LADDER[9].name} moved from Elite to Untitled division`,
      "Merged Untitled division into Elite",
      "Set a crest for Elite",
      "Rank ranges are now a custom scale"
    ]);

    const custom = apply(newEraDraft(), [
      { type: "setFloor", bandIndex: 4, rankMin: 1650 },
      { type: "link", bandIndex: 0, from: 0, to: 2 },
      { type: "unlink", bandIndex: 2 },
      { type: "split", bandIndex: 5 }
    ]);
    expect(describeEdits(custom)).toEqual([
      "Division 5 now starts at 1650",
      `Linked ${LADDER[0].name} – ${LADDER[2].name} to Division 1`,
      "Unlinked Division 3 from the OW ladder",
      "Split Division 6 — the new division takes 1500–1574"
    ]);
  });
});
