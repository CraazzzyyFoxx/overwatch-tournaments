import { kindOf } from "@/lib/flow/kinds";
import { describeAggregate, type AggregateWords } from "@/lib/flow/leaderboardTable";
import type { FlowNodeRead, FlowRead } from "@/types/flow.types";

export type FormationMode = "balancer" | "draft" | "registered" | "manual";
export type StepState = "done" | "current" | "upcoming";

/** What a pure node or a formation between two stages says to a reader, in the words of its config. */
export type FormatTransition =
  | { kind: "top"; n: number }
  | { kind: "perItemTop"; n: number; upper: number | null }
  | { kind: "range"; from: number; to: number }
  | { kind: "swissStatus"; status: "qualified" | "eliminated" }
  | { kind: "manual" }
  | { kind: "split"; buckets: string[] }
  | { kind: "reform"; mode: FormationMode };

export type FormatStageRef = { stageId: number | null; name: string };

/** One step: a stage, parallel stages of the same depth, or the match days of a league. */
export type FormatStep = {
  key: string;
  state: StepState;
  stages: FormatStageRef[];
  /** What happens between the previous step and this one; empty for the first. */
  transitions: FormatTransition[];
  /** Set for a league: `stages` are its match days and the rule is the aggregate that counts them. */
  league: { rule: AggregateWords } | null;
};

export type FormatIntro = { intake: "solo" | "team"; formation: FormationMode | null };
export type FormatSummary = { intro: FormatIntro | null; steps: FormatStep[] };

/** A step is done when all its stages are, current when it is the first one not done after play began. */
function withProgress(
  steps: Omit<FormatStep, "state">[],
  statuses: (readonly string[])[]
): FormatStep[] {
  const done = statuses.map((s) => s.length > 0 && s.every((x) => x === "completed"));
  const started = statuses.some((s) => s.some((x) => x === "completed" || x === "live"));
  const current = started ? done.indexOf(false) : -1;
  return steps.map((step, i) => ({
    ...step,
    state: done[i] ? "done" : i === current ? "current" : "upcoming"
  }));
}

/** The fallback for a tournament without flow data: the stage waves (stages sharing an `order`) as plain steps. */
export function summarizeStageWaves(
  waves: readonly (readonly { id: number; name: string; status: string }[])[]
): FormatSummary {
  return {
    intro: null,
    steps: withProgress(
      waves.map((wave) => ({
        key: wave.map((s) => s.id).join("-"),
        stages: wave.map((s) => ({ stageId: s.id, name: s.name })),
        transitions: [],
        league: null
      })),
      waves.map((wave) => wave.map((s) => s.status))
    )
  };
}

/**
 * The public "how it's played" steps, read off the flow graph. A step is a stage (stages at the same depth, e.g. divisions,
 * share one); a league (an aggregate fed by two or more stages) is ONE step; the pure nodes and formations between two
 * steps become its transitions; registration and the first formation become the intro.
 */
export function summarizeFormat(flow: FlowRead): FormatSummary {
  const nodes = new Map(flow.nodes.map((n) => [n.id, n]));
  const sources = new Map<number, number[]>();
  for (const e of flow.edges) {
    if (nodes.has(e.source_node_id) && nodes.has(e.target_node_id))
      sources.set(e.target_node_id, [...(sources.get(e.target_node_id) ?? []), e.source_node_id]);
  }
  const up = (id: number) => (sources.get(id) ?? []).sort((a, b) => a - b);
  const kind = (id: number) => kindOf(nodes.get(id)!);

  // Stages upstream of a node, counting itself: a stage's depth, and a formation's "has a stage before it".
  const depths = new Map<number, number>();
  const depth = (id: number): number => {
    const known = depths.get(id);
    if (known !== undefined) return known;
    depths.set(id, 0); // breaks a cycle; the server only saves a DAG
    const value = Math.max(0, ...up(id).map(depth)) + (kind(id) === "stage" ? 1 : 0);
    depths.set(id, value);
    return value;
  };

  const leagueOf = new Map<number, FlowNodeRead>();
  for (const node of flow.nodes) {
    if (kindOf(node) !== "aggregate") continue;
    const days = up(node.id).filter((id) => kind(id) === "stage");
    if (days.length >= 2) for (const day of days) if (!leagueOf.has(day)) leagueOf.set(day, node);
  }

  const groups = new Map<
    string,
    { depth: number; stages: FlowNodeRead[]; league: FlowNodeRead | null }
  >();
  for (const node of [...flow.nodes].sort((a, b) => a.id - b.id)) {
    if (kindOf(node) !== "stage") continue;
    const league = leagueOf.get(node.id) ?? null;
    const key = league ? `league-${league.id}` : `depth-${depth(node.id)}`;
    const group = groups.get(key) ?? { depth: Infinity, stages: [], league };
    group.depth = Math.min(group.depth, depth(node.id));
    group.stages.push(node);
    groups.set(key, group);
  }
  const ordered = [...groups.entries()].sort(([, a], [, b]) => a.depth - b.depth);

  /** Nodes between the previous step and these stages, upstream first. */
  const between = (stages: FlowNodeRead[]): FormatTransition[] => {
    const seen = new Set<number>();
    const found: FlowNodeRead[] = [];
    const visit = (id: number) => {
      for (const from of up(id)) {
        if (seen.has(from) || kind(from) === "stage") continue;
        seen.add(from);
        visit(from);
        found.push(nodes.get(from)!);
      }
    };
    stages.forEach((s) => visit(s.id));
    return found.flatMap((n) => transitionOf(n, depth(n.id) > 0));
  };

  const steps = ordered.map(([key, group], i) => ({
    key,
    stages: group.stages.map((s) => ({ stageId: s.stage_id, name: s.name })),
    transitions: i === 0 ? [] : between(group.stages),
    league: group.league ? { rule: describeAggregate(group.league.config) } : null
  }));

  const registration = flow.nodes
    .filter((n) => kindOf(n) === "registration")
    .sort((a, b) => a.id - b.id)[0];
  const formation = flow.nodes
    .filter((n) => kindOf(n) === "formation" && depth(n.id) === 0)
    .sort((a, b) => a.id - b.id)[0];
  const intake = registration?.config.intake === "team" ? "team" : "solo";
  const mode = formation ? (formation.config.mode as FormationMode) : null;

  return {
    intro: registration
      ? { intake, formation: intake === "team" && mode === "registered" ? null : mode }
      : null,
    steps: withProgress(
      steps,
      ordered.map(([, group]) => group.stages.map((s) => s.status))
    )
  };
}

function transitionOf(node: FlowNodeRead, afterStage: boolean): FormatTransition[] {
  const c = node.config as Record<string, unknown>;
  switch (kindOf(node)) {
    case "filter":
      switch (c.mode) {
        case "top":
          return [{ kind: "top", n: Number(c.n) }];
        case "per_item_top":
          return [
            {
              kind: "perItemTop",
              n: Number(c.n),
              upper: typeof c.upper === "number" ? c.upper : null
            }
          ];
        case "range":
          return [{ kind: "range", from: Number(c.from), to: Number(c.to) }];
        case "swiss_status":
          return [
            {
              kind: "swissStatus",
              status: c.swiss_status === "eliminated" ? "eliminated" : "qualified"
            }
          ];
        default:
          return [{ kind: "manual" }];
      }
    case "split":
      return [
        { kind: "split", buckets: ((c.buckets ?? []) as { name: string }[]).map((b) => b.name) }
      ];
    case "formation":
      return afterStage ? [{ kind: "reform", mode: c.mode as FormationMode }] : [];
    default:
      return [];
  }
}
