import { kindOf } from "@/lib/flow/kinds";
import type { FlowNodeRead, FlowRead } from "@/types/flow.types";

export type TableColumn = { nodeId: number; name: string };
export type TableCell = { place: number; score: number; counted: boolean } | null;
export type TableRow = {
  key: string;
  place: number;
  tied: boolean;
  name: string;
  total: number | null;
  cells: TableCell[];
  tentative: boolean;
};
export type LeaderboardTableModel = {
  node: FlowNodeRead;
  aggregate: FlowNodeRead | null;
  columns: TableColumn[];
  rows: TableRow[];
  final: boolean;
};

type Result = FlowRead["results"][number];

const participantKey = (r: Result) =>
  r.workspace_member_id != null
    ? `m${r.workspace_member_id}`
    : r.team_id != null
      ? `t${r.team_id}`
      : `i${r.stage_item_id}`;

const ranking = (flow: FlowRead, nodeId: number) =>
  flow.results
    .filter((r) => r.node_id === nodeId && r.port === "ranking")
    .sort((a, b) => a.rank - b.rank);

/** One breakdown entry per aggregate input the participant has a row in; tolerant of anything else the server stored. */
function breakdownOf(result: Result | undefined): Map<number, NonNullable<TableCell>> {
  const cells = new Map<number, NonNullable<TableCell>>();
  if (!result || !Array.isArray(result.breakdown)) return cells;
  for (const entry of result.breakdown as Record<string, unknown>[]) {
    cells.set(Number(entry.node_id), {
      place: Number(entry.place),
      score: Number(entry.score),
      counted: entry.counted === true
    });
  }
  return cells;
}

/**
 * The public table: the `leaderboard` node with the highest id (or `nodeId`, an aggregate or leaderboard) orders the rows;
 * the aggregate that feeds it supplies one column per input, the cells and the total.
 */
export function buildLeaderboardTable(
  flow: FlowRead,
  nodeId?: number
): LeaderboardTableModel | null {
  const node =
    nodeId === undefined
      ? flow.nodes.filter((n) => kindOf(n) === "leaderboard").sort((a, b) => b.id - a.id)[0]
      : flow.nodes.find((n) => n.id === nodeId);
  if (!node || (kindOf(node) !== "leaderboard" && kindOf(node) !== "aggregate")) return null;

  const source = flow.edges.find((e) => e.target_node_id === node.id);
  const upstream = source && flow.nodes.find((n) => n.id === source.source_node_id);
  const aggregate =
    kindOf(node) === "aggregate"
      ? node
      : upstream && kindOf(upstream) === "aggregate"
        ? upstream
        : null;

  const columns: TableColumn[] = aggregate
    ? flow.edges
        .filter((e) => e.target_node_id === aggregate.id)
        .sort((a, b) => a.id - b.id)
        .map((e) => ({
          nodeId: e.source_node_id,
          name: flow.nodes.find((n) => n.id === e.source_node_id)?.name ?? `#${e.source_node_id}`
        }))
    : [];

  const names = new Map<string, string>();
  for (const p of flow.participants ?? []) {
    if (p.workspace_member_id != null) names.set(`m${p.workspace_member_id}`, p.name);
    else if (p.team_id != null) names.set(`t${p.team_id}`, p.name);
  }
  const aggregateRows = new Map(
    aggregate ? ranking(flow, aggregate.id).map((r) => [participantKey(r), r]) : []
  );
  const own = ranking(flow, node.id);
  const groupSize = new Map<number, number>();
  for (const r of own)
    if (r.tie_group != null) groupSize.set(r.tie_group, (groupSize.get(r.tie_group) ?? 0) + 1);

  const rows = own.map((r): TableRow => {
    const key = participantKey(r);
    const scored = aggregateRows.get(key);
    const cells = breakdownOf(scored);
    return {
      key,
      place: r.tie_group ?? r.rank,
      tied: r.tie_group != null && (groupSize.get(r.tie_group) ?? 0) > 1,
      name: names.get(key) ?? `#${r.workspace_member_id ?? r.team_id ?? r.stage_item_id}`,
      total: scored?.score ?? r.score,
      cells: columns.map((c) => cells.get(c.nodeId) ?? null),
      tentative: `${r.state}` !== "final"
    };
  });

  return {
    node,
    aggregate,
    columns,
    rows,
    final: rows.length > 0 && rows.every((r) => !r.tentative)
  };
}

const MODES = {
  sum_all: "sumAll",
  sum_last_n: "sumLastN",
  sum_best_n: "sumBestN",
  average: "average"
} as const;
const SCORES = {
  stage_points: "stagePoints",
  placement_table: "placementTable",
  formula: "formula"
} as const;

export interface AggregateWords {
  mode: { key: "sumAll" | "sumLastN" | "sumBestN" | "average"; n: number | null };
  score: {
    key: "stagePoints" | "placementTable" | "formula";
    table: [string, number][];
    formula: string | null;
  };
}

/** The aggregate config as the keys of its three sentences (mode, score; the tiebreak sentence is fixed). */
export function describeAggregate(config: Record<string, unknown>): AggregateWords {
  const mode = MODES[config.mode as keyof typeof MODES] ?? "sumAll";
  const score = (config.score ?? {}) as {
    preset?: string;
    table?: Record<string, number>;
    formula?: string;
  };
  const key = SCORES[score.preset as keyof typeof SCORES] ?? "stagePoints";
  return {
    mode: {
      key: mode,
      n:
        (mode === "sumLastN" || mode === "sumBestN") && typeof config.n === "number"
          ? config.n
          : null
    },
    score: {
      key,
      table:
        key === "placementTable"
          ? Object.entries(score.table ?? {}).sort(([a], [b]) => Number(a) - Number(b))
          : [],
      formula: key === "formula" ? (score.formula ?? null) : null
    }
  };
}

/** The variables an aggregate formula may read (`AGGREGATE_VARIABLES` on the backend). */
export const FORMULA_VARIABLES = [
  "place",
  "participants",
  "points",
  "wins",
  "draws",
  "losses",
  "map_diff",
  "buchholz",
  "ffa_score"
] as const;
export type FormulaVariable = (typeof FORMULA_VARIABLES)[number];

const isFormulaVariable = (name: string): name is FormulaVariable =>
  (FORMULA_VARIABLES as readonly string[]).includes(name);

/**
 * A formula as a reader says it: known variables take their `label`, `*` reads `×`, `+` and `/` get a space either side.
 * Anything else (numbers, `-`, parentheses, function names) stays as written.
 */
export function formulaInWords(
  formula: string,
  label: (variable: FormulaVariable) => string
): string {
  return formula
    .replace(/\b[A-Za-z_]\w*\b/g, (name) => (isFormulaVariable(name) ? label(name) : name))
    .replace(/\s*\*\s*/g, " × ")
    .replace(/\s*([+/])\s*/g, " $1 ")
    .trim();
}
