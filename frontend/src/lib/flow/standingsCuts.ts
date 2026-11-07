import type { FlowRead } from "@/types/flow.types";

import { kindOf } from "./kinds";

/** The places a group's table is cut after: who advances, and of them who starts in the upper bracket. */
export type StandingsCuts = { advance: number[]; upper: number[] };

const sorted = (values: Set<number>) => [...values].sort((a, b) => a - b);

/**
 * Where the filters fed by a stage's ranking cut one of its groups. `per_item_top` cuts every group (its per-group
 * overrides included); `top` ranks the whole stage, so it cuts a table only while the stage is one group. Other
 * modes (range, Swiss status, a manual pick) draw nothing: they are no place boundary.
 */
export function standingsCuts(
  flow: Pick<FlowRead, "nodes" | "edges"> | undefined,
  stage: { id: number; items?: readonly unknown[] | null },
  itemId: number | null | undefined
): StandingsCuts {
  const advance = new Set<number>();
  const upper = new Set<number>();
  const stageNode = flow?.nodes.find((node) => kindOf(node) === "stage" && node.stage_id === stage.id);
  if (!flow || !stageNode) return { advance: [], upper: [] };

  const filterIds = new Set(
    flow.edges
      .filter((edge) => edge.source_node_id === stageNode.id && edge.source_port === "ranking")
      .map((edge) => edge.target_node_id)
  );
  for (const node of flow.nodes) {
    if (!filterIds.has(node.id) || kindOf(node) !== "filter") continue;
    const config = node.config;
    const perItem = (key: string) =>
      itemId == null ? undefined : (config[key] as Record<string, number> | undefined)?.[String(itemId)];
    let n: unknown;
    let up: unknown;
    if (config.mode === "per_item_top") {
      n = perItem("per_item") ?? config.n;
      up = perItem("per_item_upper") ?? config.upper;
    } else if (config.mode === "top" && (stage.items?.length ?? 0) <= 1) {
      n = config.n;
      up = config.upper;
    } else continue;
    if (typeof n !== "number" || n <= 0) continue;
    advance.add(n);
    if (typeof up === "number" && up > 0 && up < n) upper.add(up);
  }
  return { advance: sorted(advance), upper: sorted(upper) };
}
