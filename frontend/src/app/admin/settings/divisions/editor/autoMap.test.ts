// What "AUTO · 67%" and "SPLIT · choose" mean, and why only the second stops a
// publish. An old division becomes the new one sharing most of its rank range;
// the mapping is only ambiguous where the old range was cut and no new division
// holds a majority. Getting that wrong either buries the user in decisions or
// silently sends a tournament's players into the wrong division — and a rule
// set whose weights do not sum to 1 is refused by the backend outright.
import { describe, expect, it } from "vitest";

import type { DivisionTier } from "@/types/workspace.types";

import { autoMap, mappingRules, primaryTarget, unresolvedRows } from "./autoMap";
import { bandsFromTiers, LADDER, RANK_COUNT, type Band } from "./draftReducer";

const LAST = RANK_COUNT - 1;

/** Stored tiers, each spanning ladder indices `from … to` on the OW scale. */
function ladderTiers(spec: [id: number, name: string, from: number, to: number][]): DivisionTier[] {
  return spec.map(([id, name, from, to], index) => ({
    id,
    slug: name.toLowerCase(),
    number: index + 1,
    name,
    rank_min: LADDER[to].rank_min,
    rank_max: LADDER[from].rank_max,
    sort_order: index,
    icon_url: "https://cdn/x.png"
  }));
}

const OLD = ladderTiers([
  [1, "Old", 0, 1],
  [2, "Rest", 2, LAST]
]);

/** "New Era x5": twenty divisions of 100 on 100 … 2099. */
function newEra(idBase: number): DivisionTier[] {
  return Array.from({ length: 20 }, (_, index) => {
    const number = index + 1;
    const rankMin = 2100 - 100 * number;
    return {
      id: idBase + number,
      slug: `division-${number}`,
      number,
      name: `Division ${number}`,
      rank_min: rankMin,
      rank_max: number === 1 ? null : rankMin + 99,
      sort_order: index,
      icon_url: "https://cdn/x.png"
    };
  });
}

describe("autoMap", () => {
  it("maps a whole source division onto its container at full coverage", () => {
    const targets = bandsFromTiers(ladderTiers([[10, "Champion", 0, 1], [11, "Field", 2, LAST]]));
    const rows = autoMap(OLD, targets);

    expect(rows[0]).toMatchObject({ kind: "auto", coverage: 1 });
    expect(rows[0].candidates.map((candidate) => candidate.band.id)).toEqual([10]);
    expect(primaryTarget(rows[0], {}, targets)?.id).toBe(10);
  });

  it("still resolves automatically when one target holds the majority", () => {
    // Champion 1–3 cut 2 / 1: 67 %, no decision. The open-ended top counts as one
    // ladder rank wide, exactly as the ladder does.
    const source = ladderTiers([[1, "Old", 0, 2], [2, "Rest", 3, LAST]]);
    const targets = bandsFromTiers(ladderTiers([[10, "Contender", 0, 1], [11, "Field", 2, LAST]]));
    const rows = autoMap(source, targets);

    expect(rows[0].kind).toBe("auto");
    expect(Math.round(rows[0].coverage * 100)).toBe(67);
    expect(primaryTarget(rows[0], {}, targets)?.id).toBe(10);
  });

  it("asks for a decision only when the leading candidates tie", () => {
    const targets = bandsFromTiers(
      ladderTiers([[10, "Upper", 0, 0], [11, "Lower", 1, 1], [12, "Field", 2, LAST]])
    );
    const rows = autoMap(OLD, targets);

    expect(rows[0].kind).toBe("split");
    expect(primaryTarget(rows[0], {}, targets)).toBeNull();
    expect(unresolvedRows(rows, {}, targets)).toHaveLength(1);
    expect(unresolvedRows(rows, { 1: 11 }, targets)).toHaveLength(0);
  });

  it("measures overlap on the grid's own scale, so no division of a custom grid is lost", () => {
    // Division 5 (1600–1699) halved; everything else unchanged. Read through the
    // OW ladder, Divisions 17–20 had no rows at all and could never be mapped.
    const draft = newEra(100);
    draft.splice(4, 1, { ...draft[4], rank_min: 1650 }, {
      ...draft[4],
      id: 999,
      slug: "division-1600",
      name: "Division 5b",
      rank_min: 1600,
      rank_max: 1649
    });
    const targets = bandsFromTiers(draft);
    const rows = autoMap(newEra(0), targets);

    expect(rows).toHaveLength(20);
    expect(rows[0]).toMatchObject({ kind: "auto", coverage: 1 });
    expect(rows[4].kind).toBe("split");
    expect(rows.slice(16).map((row) => primaryTarget(row, {}, targets)?.id)).toEqual([
      117, 118, 119, 120
    ]);
  });

  it("writes weights that sum to 1 with exactly one primary, and nothing for an open row", () => {
    const targets = bandsFromTiers(
      ladderTiers([[10, "A", 0, 0], [11, "B", 1, 1], [12, "C", 2, 2], [13, "Field", 3, LAST]])
    );
    const rows = autoMap(ladderTiers([[1, "Old", 0, 2], [2, "Rest", 3, LAST]]), targets);

    // The three-way tie contributes nothing until chosen, which keeps the
    // mapping incomplete instead of guessing on the user's behalf.
    expect(mappingRules(rows, {}, targets).map((rule) => rule.source_tier_id)).toEqual([2]);

    const forOld = mappingRules(rows, { 1: 11 }, targets).filter((rule) => rule.source_tier_id === 1);
    expect(forOld).toHaveLength(3);
    expect(forOld.filter((rule) => rule.is_primary).map((rule) => rule.target_tier_id)).toEqual([11]);
    // Rounded like the backend checks it: round(sum, 6) must be exactly 1.
    const total = forOld.reduce((sum, rule) => sum + rule.weight, 0);
    expect(Math.round(total * 1e6) / 1e6).toBe(1);
  });

  it("takes a primary outside the overlap as the whole mapping, and drops a stale choice", () => {
    const targets = bandsFromTiers(ladderTiers([[10, "Champion", 0, 1], [11, "Field", 2, LAST]]));
    const rows = autoMap(OLD, targets);

    // Across a scale change overlap is only a guess: the organiser's pick wins.
    expect(mappingRules([rows[1]], { 2: 10 }, targets)).toEqual([
      { source_tier_id: 2, target_tier_id: 10, weight: 1, is_primary: true }
    ]);
    // A stored pick naming a division that was merged away falls back to AUTO.
    expect(primaryTarget(rows[0], { 1: 404 }, targets)?.id).toBe(10);
  });

  it("skips a target that has no id yet — an unsaved draft cannot be mapped", () => {
    const unsaved: Band = {
      slug: "fresh",
      name: "Untitled division",
      number: 1,
      icon_url: null,
      rankMin: LADDER[LAST].rank_min,
      rankMax: null,
      ow: { from: 0, to: LAST }
    };
    const rows = autoMap(ladderTiers([[1, "Old", 0, LAST]]), [unsaved]);

    expect(rows[0].kind).toBe("auto");
    expect(mappingRules(rows, {}, [unsaved])).toEqual([]);
  });
});
