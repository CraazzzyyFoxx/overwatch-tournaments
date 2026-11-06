import { kindOf } from "@/lib/flow/kinds";
import type { FlowRead } from "@/types/flow.types";

export type BracketBranch = { key: string; label: string; stageIds: number[] };

/**
 * A stage's branch is the set of `registration` nodes upstream of it (Decision 7). Branches run single-intake days first,
 * combined finals after; fewer than two means the tournament has no branch row.
 */
export function bracketBranches(flow: FlowRead | undefined): BracketBranch[] {
  if (!flow) return [];
  const byId = new Map(flow.nodes.map((n) => [n.id, n]));
  const upstream = new Map<number, number[]>();
  for (const e of flow.edges)
    upstream.set(e.target_node_id, [...(upstream.get(e.target_node_id) ?? []), e.source_node_id]);

  const registrations = (start: number): number[] => {
    const seen = new Set<number>();
    const found: number[] = [];
    const queue = [start];
    for (let id = queue.pop(); id !== undefined; id = queue.pop()) {
      for (const from of upstream.get(id) ?? []) {
        if (seen.has(from)) continue;
        seen.add(from);
        if (byId.get(from) && kindOf(byId.get(from)!) === "registration") found.push(from);
        queue.push(from);
      }
    }
    return found.sort((a, b) => a - b);
  };

  const branches = new Map<string, { regs: number[]; stageIds: number[] }>();
  for (const node of [...flow.nodes].sort((a, b) => a.id - b.id)) {
    if (kindOf(node) !== "stage" || node.stage_id == null) continue;
    const regs = registrations(node.id);
    if (regs.length === 0) continue;
    const key = regs.join(",");
    const branch = branches.get(key) ?? { regs, stageIds: [] };
    branch.stageIds.push(node.stage_id);
    branches.set(key, branch);
  }
  if (branches.size < 2) return [];
  return [...branches.entries()]
    .sort(([, a], [, b]) => a.regs.length - b.regs.length || a.regs[0] - b.regs[0])
    .map(([key, { regs, stageIds }]) => ({
      key,
      label: regs.map((id) => byId.get(id)?.name ?? `#${id}`).join(" + "),
      stageIds
    }));
}

export const branchOf = (
  branches: BracketBranch[],
  stageId: number | null
): BracketBranch | null =>
  stageId === null ? null : (branches.find((b) => b.stageIds.includes(stageId)) ?? null);
