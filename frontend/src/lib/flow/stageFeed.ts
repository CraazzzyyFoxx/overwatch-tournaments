import type {
  FlowChanges,
  FlowNodeKind,
  FlowNodeRead,
  FlowNodeUpsert,
  FlowRead,
  FlowStageCreate
} from "@/types/flow.types";

import { kindOf } from "./kinds";

/** What the Bracket tab can say about who a stage takes in: the rule behind a stage's `participants` input. */
export const FEED_MODES = ["all", "top", "per_item_top", "swiss_status"] as const;
export type FeedMode = (typeof FEED_MODES)[number];

export type FeedRule = {
  mode: FeedMode;
  n: number;
  /** Double elimination target, `per_item_top` only: how many per group start in the upper bracket. */
  upper: number | null;
  swissStatus: "qualified" | "eliminated";
};

type Graph = Pick<FlowRead, "nodes" | "edges">;

/**
 * A stage's input as Bracket reads it. Only `none`, `direct` and `filter` are editable here; `entry` and `complex` are
 * shown and never rewritten. `sources` name the nodes that feed the stage straight in. `formed` is a stage fed by a
 * formation: `inner` reads the formation's own input the same way, so a re-formation still names the stage before it.
 */
export type StageFeed = InputFeed | { kind: "formed"; formation: FlowNodeRead; inner: InputFeed };

type InputFeed =
  | { kind: "none" }
  | { kind: "entry"; sources: string[] }
  | { kind: "direct"; sourceStageNodeId: number; edgeId: number }
  | { kind: "filter"; filter: FlowNodeRead; sourceStageNodeId: number; edgeIds: [number, number] }
  | { kind: "complex"; sources: { kind: FlowNodeKind; name: string }[] };

export type FeedChoice = { source: number | null; rule: FeedRule };

const FILTER_MODES: readonly string[] = ["top", "per_item_top", "swiss_status"];
const X_STEP = 300;
// The generated kind is a TS enum; the literals below are its values.
const asKind = (kind: "filter" | "stage") => kind as FlowNodeUpsert["kind"];

export const defaultRule = (source: { items: readonly unknown[] } | undefined): FeedRule => ({
  mode: source && source.items.length > 1 ? "per_item_top" : "all",
  n: 2,
  upper: null,
  swissStatus: "qualified"
});

/** The rule a filter node's config carries, or null when it says more than Bracket can (a range, a manual pick, per-group overrides). */
function ruleOfFilter(config: FlowNodeRead["config"]): FeedRule | null {
  const mode = config.mode as string;
  // A per-group value equal to the general one (migrated tournaments carry them) overrides nothing.
  const overrides = (value: unknown, general: unknown) =>
    Object.values((value as Record<string, unknown> | undefined) ?? {}).some((each) => each !== general);
  if (!FILTER_MODES.includes(mode) || overrides(config.per_item, config.n) || overrides(config.per_item_upper, config.upper))
    return null;
  return {
    mode: mode as FeedMode,
    n: typeof config.n === "number" ? config.n : 1,
    upper: typeof config.upper === "number" ? config.upper : null,
    swissStatus: config.swiss_status === "eliminated" ? "eliminated" : "qualified"
  };
}

/** The input of a stage or a formation: nothing, a registration/formation, a stage straight or through one filter, or more. */
function classifyInput(graph: Graph, nodeId: number): InputFeed {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const incoming = graph.edges.filter((edge) => edge.target_node_id === nodeId);
  if (incoming.length === 0) return { kind: "none" };

  const sources = incoming.flatMap((edge) => nodes.get(edge.source_node_id) ?? []);
  if (incoming.length === 1) {
    const [edge] = incoming;
    const source = nodes.get(edge.source_node_id);
    if (source && kindOf(source) === "stage" && edge.source_port === "ranking") {
      return { kind: "direct", sourceStageNodeId: source.id, edgeId: edge.id };
    }
    if (source && kindOf(source) === "filter" && edge.source_port === "passed" && ruleOfFilter(source.config)) {
      const fed = graph.edges.filter((e) => e.target_node_id === source.id);
      const shared = graph.edges.some((e) => e.source_node_id === source.id && e.id !== edge.id);
      const feeder = fed.length === 1 ? nodes.get(fed[0].source_node_id) : undefined;
      if (!shared && feeder && kindOf(feeder) === "stage" && fed[0].source_port === "ranking" && fed[0].target_port === "ranking") {
        return { kind: "filter", filter: source, sourceStageNodeId: feeder.id, edgeIds: [fed[0].id, edge.id] };
      }
    }
  }
  if (sources.length > 0 && sources.every((node) => ["formation", "registration"].includes(kindOf(node)))) {
    return { kind: "entry", sources: sources.map((node) => node.name) };
  }
  return { kind: "complex", sources: sources.map((node) => ({ kind: kindOf(node), name: node.name })) };
}

export function classifyStageFeed(graph: Graph, stageNodeId: number): StageFeed {
  const incoming = graph.edges.filter((edge) => edge.target_node_id === stageNodeId);
  const formation =
    incoming.length === 1 && incoming[0].source_port === "teams"
      ? graph.nodes.find((node) => node.id === incoming[0].source_node_id && kindOf(node) === "formation")
      : undefined;
  return formation ? { kind: "formed", formation, inner: classifyInput(graph, formation.id) } : classifyInput(graph, stageNodeId);
}

/** The rule and source an editable feed currently has; through a formation, those of the formation's input. */
export function choiceOfFeed(feed: StageFeed, fallback: FeedRule): FeedChoice | null {
  if (feed.kind === "formed") return feed.inner.kind === "none" ? null : choiceOfFeed(feed.inner, fallback);
  if (feed.kind === "none") return { source: null, rule: fallback };
  if (feed.kind === "direct") return { source: feed.sourceStageNodeId, rule: { ...fallback, mode: "all" } };
  if (feed.kind === "filter") {
    return { source: feed.sourceStageNodeId, rule: ruleOfFilter(feed.filter.config) ?? fallback };
  }
  return null;
}

/** Whether two rules select the same participants; fields a mode ignores do not count. */
export function sameRule(a: FeedRule, b: FeedRule): boolean {
  if (a.mode !== b.mode) return false;
  if (a.mode === "top") return a.n === b.n;
  if (a.mode === "per_item_top") return a.n === b.n && a.upper === b.upper;
  if (a.mode === "swiss_status") return a.swissStatus === b.swissStatus;
  return true;
}

function filterConfig(rule: FeedRule): Record<string, unknown> {
  if (rule.mode === "swiss_status") return { mode: rule.mode, swiss_status: rule.swissStatus };
  if (rule.mode === "per_item_top") return { mode: rule.mode, n: rule.n, ...(rule.upper != null ? { upper: rule.upper } : {}) };
  return { mode: rule.mode, n: rule.n };
}

const edge = (source: number | string, source_port: string, target: number | string, target_port: string) =>
  ({ source, source_port, target, target_port }) as NonNullable<FlowChanges["edges"]>[number];

/** The nodes and edges that wire `source.ranking` into `target`'s input `port` under `rule`: a direct edge, or a new filter between. */
function wire(
  source: number,
  target: number | string,
  rule: FeedRule,
  filterName: string,
  at: { x: number; y: number },
  port = "participants"
): Pick<FlowChanges, "nodes" | "edges"> {
  if (rule.mode === "all") return { nodes: [], edges: [edge(source, "ranking", target, port)] };
  return {
    nodes: [{ ref: "filter", kind: asKind("filter"), name: filterName, config: filterConfig(rule), position_x: at.x, position_y: at.y }],
    edges: [edge(source, "ranking", "filter", "ranking"), edge("filter", "passed", target, port)]
  };
}

/**
 * The edit that makes `source`'s ranking feed the stage under `rule`; null when the feed is not one Bracket may rewrite
 * (`entry`, `complex`) or nothing would change. The existing filter is updated in place while the new rule is a filter
 * mode; otherwise the replaced edges and filter are deleted. Through a formation, the rule is the formation's input.
 */
export function changeStageFeed(
  graph: Graph,
  stageNodeId: number,
  choice: { source: number; rule: FeedRule },
  filterName: string
): FlowChanges | null {
  const stageFeed = classifyStageFeed(graph, stageNodeId);
  const formation = stageFeed.kind === "formed" ? stageFeed.formation : null;
  const feed = stageFeed.kind === "formed" ? stageFeed.inner : stageFeed;
  const targetId = formation ? formation.id : stageNodeId;
  const port = formation ? "players" : "participants";
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const target = nodes.get(targetId);
  const source = nodes.get(choice.source);
  if (!target || !source || feed.kind === "entry" || feed.kind === "complex") return null;
  const { source: sourceId, rule } = choice;

  if (feed.kind === "filter" && rule.mode !== "all") {
    const sourceChanged = feed.sourceStageNodeId !== sourceId;
    const ruleChanged = !sameRule(ruleOfFilter(feed.filter.config) as FeedRule, rule);
    if (!sourceChanged && !ruleChanged) return null;
    return {
      nodes: ruleChanged
        ? [{ id: feed.filter.id, kind: asKind("filter"), name: feed.filter.name, config: filterConfig(rule) }]
        : [],
      edges: sourceChanged ? [{ ...edge(sourceId, "ranking", feed.filter.id, "ranking"), id: feed.edgeIds[0] }] : []
    };
  }
  if (feed.kind === "direct" && rule.mode === "all" && feed.sourceStageNodeId === sourceId) return null;

  const wired = wire(
    sourceId,
    targetId,
    rule,
    filterName,
    { x: (source.position_x + target.position_x) / 2, y: (source.position_y + target.position_y) / 2 },
    port
  );
  return {
    ...wired,
    delete_edge_ids: feed.kind === "direct" ? [feed.edgeId] : feed.kind === "filter" ? [...feed.edgeIds] : [],
    delete_node_ids: feed.kind === "filter" ? [feed.filter.id] : []
  };
}

/** The one edit that adds a stage (with its `stage` payload) fed by `source` under `rule`, or fed by nothing when there is no source. */
export function addStageChanges(args: {
  name: string;
  stage: FlowStageCreate;
  source: FlowNodeRead | null;
  rule: FeedRule;
  filterName: string;
}): FlowChanges {
  const { name, stage, source, rule, filterName } = args;
  const x = source?.position_x ?? 0;
  const y = source?.position_y ?? 0;
  const stageX = x + (rule.mode === "all" ? 1 : 2) * X_STEP;
  const stageNode = { ref: "stage", kind: asKind("stage"), name, config: {}, stage, position_x: stageX, position_y: y };
  if (!source) return { nodes: [stageNode] };
  const wired = wire(source.id, "stage", rule, filterName, { x: x + X_STEP, y });
  return { nodes: [stageNode, ...(wired.nodes ?? [])], edges: wired.edges };
}
