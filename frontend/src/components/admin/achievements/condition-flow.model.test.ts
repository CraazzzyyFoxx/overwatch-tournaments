import { describe, expect, it } from "vitest";

import {
  appendChild,
  appendPaletteItem,
  buildNodePaths,
  flatToTree,
  removeSubtree,
  treeToFlat,
  type TreeNode,
} from "./condition-flow.model";

/** Flat nodes only round-trip through a root, so every check goes through it. */
function roundTrip(tree: TreeNode): TreeNode {
  const flat = treeToFlat(tree);
  const root = flat.find((node) => !node.parentId)!;
  return flatToTree(flat, root.id);
}

describe("condition tree ↔ flat graph", () => {
  it("round-trips a nested AND/OR/NOT tree unchanged", () => {
    const tree: TreeNode = {
      AND: [
        { type: "match_win" },
        {
          OR: [
            { type: "stat_threshold", params: { stat: "Eliminations", op: ">=", value: 20 } },
            { NOT: { type: "is_newcomer" } },
          ],
        },
      ],
    };

    expect(roundTrip(tree)).toEqual(tree);
  });

  it("drops an empty params bag so a bare condition stays bare", () => {
    expect(roundTrip({ type: "match_win", params: {} })).toEqual({ type: "match_win" });
  });

  it("turns an empty tree into a single empty AND group", () => {
    expect(roundTrip({})).toEqual({ AND: [] });
  });

  it("defaults a leaf with no type to match_win", () => {
    expect(roundTrip({ params: { foo: 1 } })).toEqual({ type: "match_win", params: { foo: 1 } });
  });

  it("keeps only the first child of a NOT group", () => {
    const flat = treeToFlat({ NOT: { type: "match_win" } });
    const withSecond = appendChild(flat, flat[0].id, "leaf");

    expect(flatToTree(withSecond, flat[0].id)).toEqual({ NOT: { type: "match_win" } });
  });
});

describe("editing the flat graph", () => {
  it("wraps a bare leaf root in an AND group when a palette item is appended", () => {
    const flat = treeToFlat({ type: "match_win" });

    const updated = appendPaletteItem(flat, { type: "leaf", conditionType: "is_captain", label: "Is captain" });
    const root = updated.find((node) => !node.parentId)!;

    expect(root.type).toBe("logical");
    expect(flatToTree(updated, root.id)).toEqual({
      AND: [{ type: "match_win" }, { type: "is_captain" }],
    });
  });

  it("appends to an existing logical root instead of wrapping it", () => {
    const flat = treeToFlat({ AND: [{ type: "match_win" }] });

    const updated = appendPaletteItem(flat, { type: "logical", logicalOp: "OR", label: "OR" });
    const root = updated.find((node) => !node.parentId)!;

    expect(flatToTree(updated, root.id)).toEqual({ AND: [{ type: "match_win" }, { OR: [] }] });
  });

  it("deletes a group together with every descendant", () => {
    const flat = treeToFlat({
      AND: [{ OR: [{ type: "match_win" }, { type: "is_captain" }] }, { type: "is_newcomer" }],
    });
    const root = flat.find((node) => !node.parentId)!;
    const orGroup = flat.find((node) => node.logicalOp === "OR")!;

    const updated = removeSubtree(flat, orGroup.id);

    expect(updated).toHaveLength(2);
    expect(flatToTree(updated, root.id)).toEqual({ AND: [{ type: "is_newcomer" }] });
  });

  it("names every node by its position in the tree", () => {
    const flat = treeToFlat({ AND: [{ OR: [{ type: "match_win" }] }, { type: "is_captain" }] });

    const paths = buildNodePaths(flat);

    expect(Object.values(paths).sort()).toEqual(["1", "1.1", "1.1.1", "1.2"]);
  });
});
