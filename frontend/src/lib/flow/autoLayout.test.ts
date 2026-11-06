import { describe, expect, it } from "vitest";

import { arrangeDraft, arrangeIfOverlapping, autoLayout, hasOverlap } from "./autoLayout";
import { draftFromRead } from "./flowDraft";
import { starterRead } from "./fixtures";

const node = (key: string, y = 0) => ({ key, x: 0, y });
const link = (source: string, target: string) => ({ source, target });
const apart = (points: { x: number; y: number }[]) => !hasOverlap(points);
const at = (layout: Map<string, { x: number; y: number }>, key: string) => layout.get(key)!;

describe("autoLayout", () => {
  it("puts a chain on one row, one column per step", () => {
    const layout = autoLayout([node("a"), node("b"), node("c")], [link("a", "b"), link("b", "c")]);
    const [a, b, c] = ["a", "b", "c"].map((k) => at(layout, k));
    expect(a.x).toBeLessThan(b.x);
    expect(b.x).toBeLessThan(c.x);
    expect(new Set([a.y, b.y, c.y]).size).toBe(1);
    expect(apart([a, b, c])).toBe(true);
  });

  it("stacks parallel branches in their current vertical order and centres the single node after them", () => {
    const layout = autoLayout(
      [node("src"), node("low", 300), node("high", 10), node("sink")],
      [link("src", "low"), link("src", "high"), link("low", "sink"), link("high", "sink")]
    );
    expect(at(layout, "high").y).toBeLessThan(at(layout, "low").y);
    expect(at(layout, "high").x).toBe(at(layout, "low").x);
    expect(at(layout, "sink").x).toBeGreaterThan(at(layout, "low").x);
    expect(at(layout, "src").y).toBe(at(layout, "sink").y);
    expect(at(layout, "src").y).toBeGreaterThan(at(layout, "high").y - 1);
    expect(at(layout, "src").y).toBeLessThan(at(layout, "low").y + 1);
  });

  it("puts a merge one column past its deepest input (longest path)", () => {
    const layout = autoLayout(
      [node("a"), node("b"), node("c"), node("merge")],
      [link("a", "b"), link("b", "c"), link("a", "merge"), link("c", "merge")]
    );
    expect(at(layout, "merge").x).toBeGreaterThan(at(layout, "c").x);
  });

  it("lays eight league days into one aggregate without overlaps", () => {
    const days = Array.from({ length: 8 }, (_, i) => node(`day${i}`, 0));
    const nodes = [...days, node("aggregate"), node("board")];
    const edges = [...days.map((d) => link(d.key, "aggregate")), link("aggregate", "board")];
    const layout = autoLayout(nodes, edges);
    expect(new Set(days.map((d) => at(layout, d.key).x)).size).toBe(1);
    expect(new Set(days.map((d) => at(layout, d.key).y)).size).toBe(8);
    expect(at(layout, "aggregate").x).toBeGreaterThan(at(layout, "day0").x);
    expect(apart([...layout.values()])).toBe(true);
  });

  it("orders equal rows by key and survives a cycle", () => {
    const tie = autoLayout([node("10"), node("2")], []);
    expect(at(tie, "2").y).toBeLessThan(at(tie, "10").y);
    expect(autoLayout([node("a"), node("b")], [link("a", "b"), link("b", "a")]).size).toBe(2);
  });
});

describe("hasOverlap / arrangeDraft", () => {
  it("flags cards closer than a narrow card is wide, and nothing else", () => {
    expect(hasOverlap([{ x: 0, y: 0 }, { x: 150, y: 0 }])).toBe(true);
    expect(hasOverlap([{ x: 0, y: 0 }, { x: 260, y: 0 }])).toBe(false);
    expect(hasOverlap([{ x: 0, y: 0 }, { x: 0, y: 200 }])).toBe(false);
  });

  it("leaves a draft with no overlapping cards alone", () => {
    const draft = draftFromRead(starterRead());
    expect(arrangeIfOverlapping(draft)).toBe(draft);
  });

  it("moves overlapping nodes and keeps the base, so the moves are unsaved changes", () => {
    const read = starterRead();
    read.nodes[1].position_x = 100;
    const draft = draftFromRead(read);
    const arranged = arrangeIfOverlapping(draft);
    expect(hasOverlap(arranged.nodes)).toBe(false);
    expect(arranged.base).toBe(draft.base);
    expect(arrangeDraft(arranged)).toBe(arranged);
  });
});
