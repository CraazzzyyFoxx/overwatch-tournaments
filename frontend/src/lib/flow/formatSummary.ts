import { kindOf } from "@/lib/flow/kinds";
import { describeAggregate, type AggregateWords } from "@/lib/flow/leaderboardTable";
import type { FlowNodeRead, FlowRead } from "@/types/flow.types";
import type { StageSummary } from "@/types/tournament.types";

export type FormationMode = "balancer" | "draft" | "registered" | "manual";
export type StepState = "done" | "current" | "upcoming";

/** What a pure node between two stages says to a reader, in the words of its config. */
export type FormatTransition =
  | { kind: "top"; n: number }
  | { kind: "perItemTop"; n: number; upper: number | null; grouped: boolean }
  | { kind: "range"; from: number; to: number }
  | { kind: "swissStatus"; status: "qualified" | "eliminated" }
  | { kind: "manual" }
  | { kind: "split"; buckets: string[] };

/**
 * How the teams of a step are made. `renewed` is set when they are made anew inside the step (every round of an
 * individual swiss, every day of a league whose days each have a formation); `byScore` is an individual swiss
 * that groups opponents by points.
 */
export type FormatTeams = {
  mode: FormationMode;
  renewed: "round" | "day" | null;
  byScore: boolean;
};

export type FormatStageRef = { stageId: number | null; name: string };

/** One step: a stage, parallel stages of the same depth, or the match days of a league. */
export type FormatStep = {
  key: string;
  state: StepState;
  stages: FormatStageRef[];
  /** What happens between the previous step and this one; empty for the first. */
  transitions: FormatTransition[];
  /** How this step's teams are made; `null` when they carry over from the stage before. */
  teams: FormatTeams | null;
  /** Set for a league: `stages` are its match days and the rule is the aggregate that counts them. */
  league: { rule: AggregateWords } | null;
};

export type FormatIntro = { intake: "solo" | "team" };
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
        teams: null,
        league: null
      })),
      waves.map((wave) => wave.map((s) => s.status))
    )
  };
}

/**
 * The public "how it's played" steps, read off the flow graph. A step is a stage (stages at the same depth, e.g. divisions,
 * share one); a league (an aggregate fed by two or more stages) is ONE step; the pure nodes between two steps become
 * its transitions and the formation feeding a step says how its teams are made; registration becomes the intro.
 * `stages` (the tournament's stage summaries) tell an individual swiss, which has no formation node, from the rest.
 */
export function summarizeFormat(
  flow: FlowRead,
  stages: readonly Pick<StageSummary, "id" | "stage_type" | "pairing_mode">[] = []
): FormatSummary {
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

  /** The most distinct stage items (groups) a filter's source stages show in their results or its per-item map; 0 when unknown. */
  const itemCount = (filter: FlowNodeRead): number => {
    const sourceStages = new Set<number>();
    const walk = (id: number) => {
      for (const from of up(id)) {
        if (kind(from) === "stage") sourceStages.add(from);
        else walk(from);
      }
    };
    walk(filter.id);
    const items = new Set<string>(Object.keys((filter.config.per_item ?? {}) as object));
    for (const r of flow.results)
      if (sourceStages.has(r.node_id) && r.stage_item_id != null)
        items.add(String(r.stage_item_id));
    return items.size;
  };

  /** Non-stage nodes between the previous step and these stages, upstream first. */
  const upstream = (targets: FlowNodeRead[]): FlowNodeRead[] => {
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
    targets.forEach((s) => visit(s.id));
    return found;
  };

  const teamsOf = (group: { stages: FlowNodeRead[]; league: FlowNodeRead | null }): FormatTeams | null => {
    // An individual swiss has no formation node: the balancer deals new teams every round.
    const swiss = group.stages
      .map((s) => stages.find((x) => x.id === s.stage_id))
      .find((x) => x?.stage_type === "individual_swiss");
    if (swiss) return { mode: "balancer", renewed: "round", byScore: swiss.pairing_mode !== "balance" };
    const formations = group.stages
      .map((s) => upstream([s]).filter((n) => kindOf(n) === "formation"))
      .flat()
      .sort((a, b) => a.id - b.id);
    if (formations.length === 0) return null;
    const distinct = new Set(formations.map((n) => n.id));
    return {
      mode: formations[0]!.config.mode as FormationMode,
      renewed: group.league && distinct.size >= 2 ? "day" : null,
      byScore: false
    };
  };

  const steps = ordered.map(([key, group], i) => ({
    key,
    stages: group.stages.map((s) => ({ stageId: s.stage_id, name: s.name })),
    transitions: i === 0 ? [] : upstream(group.stages).flatMap((n) => transitionOf(n, itemCount(n))),
    teams: teamsOf(group),
    league: group.league ? { rule: describeAggregate(group.league.config) } : null
  }));

  const registration = flow.nodes
    .filter((n) => kindOf(n) === "registration")
    .sort((a, b) => a.id - b.id)[0];
  const intake = registration?.config.intake === "team" ? "team" : "solo";

  return {
    intro: registration ? { intake } : null,
    steps: withProgress(
      steps,
      ordered.map(([, group]) => group.stages.map((s) => s.status))
    )
  };
}

function transitionOf(node: FlowNodeRead, items: number): FormatTransition[] {
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
              upper: typeof c.upper === "number" ? c.upper : null,
              grouped: items >= 2
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
    default:
      return [];
  }
}
