import { updateNode, type FlowDraft } from "./flowDraft";

/** The widest a `FlowNodeCard` gets: `max-w-56` name (224) + `px-3` (24) + `border-2` (4) = 252, rounded up. */
const CARD_WIDTH = 256;
/** A card with a kind line, a name line and one badge row, with room to spare. */
const CARD_HEIGHT = 96;
const COLUMN_GAP = 80;
const ROW_GAP = 32;
const COLUMN_PITCH = CARD_WIDTH + COLUMN_GAP;
const ROW_PITCH = CARD_HEIGHT + ROW_GAP;

/** The narrowest card (`min-w-44`) and a one-badge-row card's height: two boxes this size touching are certainly overlapping. */
const MIN_WIDTH = 176;
const MIN_HEIGHT = 80;

type Point = { x: number; y: number };
type Placed = Point & { key: string };

/** Whether any two cards, at their smallest, overlap; hand-placed nodes that merely sit close stay where they are. */
export const hasOverlap = (nodes: readonly Point[]): boolean =>
  nodes.some((a, i) =>
    nodes.slice(i + 1).some((b) => Math.abs(a.x - b.x) < MIN_WIDTH && Math.abs(a.y - b.y) < MIN_HEIGHT)
  );

/**
 * Layered layout: a node's column is its longest path from a source, its row the order within the column (current `y`, then
 * key), each column centred on the tallest one. Spacing exceeds the card size, so nothing overlaps.
 */
export function autoLayout(
  nodes: readonly Placed[],
  edges: readonly { source: string; target: string }[]
): Map<string, Point> {
  const known = new Set(nodes.map((n) => n.key));
  const links = edges.filter((e) => known.has(e.source) && known.has(e.target));
  const depth = new Map(nodes.map((n) => [n.key, 0]));
  // One pass per node settles every acyclic path; the cap keeps a (rejected-by-the-server) cycle from looping.
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false;
    for (const { source, target } of links) {
      const next = (depth.get(source) as number) + 1;
      if (next > (depth.get(target) as number) && next < nodes.length) {
        depth.set(target, next);
        changed = true;
      }
    }
    if (!changed) break;
  }

  const columns = new Map<number, Placed[]>();
  for (const n of nodes) columns.set(depth.get(n.key) as number, [...(columns.get(depth.get(n.key) as number) ?? []), n]);
  const tallest = Math.max(0, ...[...columns.values()].map((c) => c.length));

  const out = new Map<string, Point>();
  for (const [column, members] of columns) {
    members.sort((a, b) => a.y - b.y || a.key.localeCompare(b.key, undefined, { numeric: true }));
    const top = ((tallest - members.length) * ROW_PITCH) / 2;
    members.forEach((n, row) => out.set(n.key, { x: column * COLUMN_PITCH, y: Math.round(top + row * ROW_PITCH) }));
  }
  return out;
}

/** The draft with every node on the layered layout; each move is an ordinary unsaved change. */
export const arrangeDraft = (draft: FlowDraft): FlowDraft => {
  const layout = autoLayout(draft.nodes, draft.edges);
  return draft.nodes.reduce((acc, n) => {
    const at = layout.get(n.key) as Point;
    return at.x === n.x && at.y === n.y ? acc : updateNode(acc, n.key, at);
  }, draft);
};

/** The draft as is, unless some cards overlap. */
export const arrangeIfOverlapping = (draft: FlowDraft): FlowDraft => (hasOverlap(draft.nodes) ? arrangeDraft(draft) : draft);
