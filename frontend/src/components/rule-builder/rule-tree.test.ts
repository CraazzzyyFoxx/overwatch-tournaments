import { describe, expect, it } from "vitest";

import {
  appendChild,
  appendPaletteItem,
  buildNodePaths,
  flatToTree,
  removeSubtree,
  treeToFlat,
  type TreeNode,
} from "./rule-tree";

/** The registry's "anything" leaf; the builder never invents one of its own. */
const FALLBACK = "match_win";

/** Flat nodes only round-trip through a root, so every check goes through it. */
function roundTrip(tree: TreeNode): TreeNode {
  const flat = treeToFlat(tree, FALLBACK);
  const root = flat.find((node) => !node.parentId)!;
  return flatToTree(flat, root.id, FALLBACK);
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

  it("round-trips a pick-ban tree, whose leaves are a different registry", () => {
    const tree: TreeNode = {
      NOT: { type: "banned_by", params: { by: "self", scope: "series" } },
    };

    expect(flatToTree(treeToFlat(tree, "item_in"), "node_1", "item_in")).toEqual(tree);
  });

  it("drops an empty params bag so a bare condition stays bare", () => {
    expect(roundTrip({ type: "match_win", params: {} })).toEqual({ type: "match_win" });
  });

  it("turns an empty tree into a single empty AND group", () => {
    expect(roundTrip({})).toEqual({ AND: [] });
  });

  it("defaults a leaf with no type to the registry's fallback", () => {
    expect(roundTrip({ params: { foo: 1 } })).toEqual({ type: FALLBACK, params: { foo: 1 } });
    const flat = treeToFlat({ params: { foo: 1 } }, "item_in");
    expect(flatToTree(flat, flat[0].id, "item_in")).toEqual({ type: "item_in", params: { foo: 1 } });
  });

  it("keeps only the first child of a NOT group", () => {
    const flat = treeToFlat({ NOT: { type: "match_win" } }, FALLBACK);
    const withSecond = appendChild(flat, flat[0].id, "leaf", FALLBACK);

    expect(flatToTree(withSecond, flat[0].id, FALLBACK)).toEqual({ NOT: { type: "match_win" } });
  });
});

describe("editing the flat graph", () => {
  it("wraps a bare leaf root in an AND group when a palette item is appended", () => {
    const flat = treeToFlat({ type: "match_win" }, FALLBACK);

    const updated = appendPaletteItem(
      flat,
      { type: "leaf", leafType: "is_captain", label: "Is captain" },
      FALLBACK
    );
    const root = updated.find((node) => !node.parentId)!;

    expect(root.type).toBe("logical");
    expect(flatToTree(updated, root.id, FALLBACK)).toEqual({
      AND: [{ type: "match_win" }, { type: "is_captain" }],
    });
  });

  it("appends to an existing logical root instead of wrapping it", () => {
    const flat = treeToFlat({ AND: [{ type: "match_win" }] }, FALLBACK);

    const updated = appendPaletteItem(flat, { type: "logical", logicalOp: "OR", label: "OR" }, FALLBACK);
    const root = updated.find((node) => !node.parentId)!;

    expect(flatToTree(updated, root.id, FALLBACK)).toEqual({
      AND: [{ type: "match_win" }, { OR: [] }],
    });
  });

  it("deletes a group together with every descendant", () => {
    const flat = treeToFlat(
      { AND: [{ OR: [{ type: "match_win" }, { type: "is_captain" }] }, { type: "is_newcomer" }] },
      FALLBACK
    );
    const root = flat.find((node) => !node.parentId)!;
    const orGroup = flat.find((node) => node.logicalOp === "OR")!;

    const updated = removeSubtree(flat, orGroup.id);

    expect(updated).toHaveLength(2);
    expect(flatToTree(updated, root.id, FALLBACK)).toEqual({ AND: [{ type: "is_newcomer" }] });
  });

  it("names every node by its position in the tree", () => {
    const flat = treeToFlat(
      { AND: [{ OR: [{ type: "match_win" }] }, { type: "is_captain" }] },
      FALLBACK
    );

    const paths = buildNodePaths(flat);

    expect(Object.values(paths).sort()).toEqual(["1", "1.1", "1.1.1", "1.2"]);
  });
});
