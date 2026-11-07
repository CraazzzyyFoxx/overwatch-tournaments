import { kindOf } from "@/lib/flow/kinds";
import type { FlowNodeRead, FlowRead } from "@/types/flow.types";

export type TableColumn = { nodeId: number; name: string };
/** One aggregate input's day for a participant; the metric fields are null when the input row did not carry them. */
export type DayCell = {
  place: number;
  score: number;
  counted: boolean;
  /** The role the participant played that day (the roster's), null when none or unknown. */
  role: string | null;
  teamId: number | null;
  wins: number | null;
  draws: number | null;
  losses: number | null;
  buchholz: number | null;
};
export type TableCell = DayCell | null;
export type TableRow = {
  key: string;
  /** The rated role this row ranks under; null unless the table is by-role (and then null = the "no role" partition). */
  role: string | null;
  /** Every role the participant played across the days, in the order `buildLeaderboardTable` was given. */
  roles: string[];
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
  /** The upstream aggregate ranks each role separately (`config.by_role`). */
  byRole: boolean;
  /** With `byRole`: the role partitions present, named roles first, the "no role" partition (null) last. */
  roles: (string | null)[];
  /** Team names by team id (`FlowRead.participants`), for a day's team. */
  teamNames: ReadonlyMap<number, string>;
};

type Result = FlowRead["results"][number];

const participantKey = (r: Result) =>
  r.workspace_member_id != null
    ? `m${r.workspace_member_id}`
    : r.team_id != null
      ? `t${r.team_id}`
      : `i${r.stage_item_id}`;

const roleOf = (r: Result): string | null => (typeof r.role === "string" && r.role ? r.role : null);

const ranking = (flow: FlowRead, nodeId: number) =>
  flow.results
    .filter((r) => r.node_id === nodeId && r.port === "ranking")
    .sort((a, b) => a.rank - b.rank);

const metric = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** One breakdown entry per aggregate input the participant has a row in; tolerant of anything else the server stored. */
function breakdownOf(result: Result | undefined): Map<number, DayCell> {
  const cells = new Map<number, DayCell>();
  if (!result || !Array.isArray(result.breakdown)) return cells;
  for (const entry of result.breakdown as Record<string, unknown>[]) {
    if (!entry || typeof entry !== "object") continue;
    cells.set(Number(entry.node_id), {
      place: Number(entry.place),
      score: Number(entry.score),
      counted: entry.counted === true,
      role: typeof entry.role === "string" && entry.role ? entry.role : null,
      teamId: metric(entry.team_id),
      wins: metric(entry.wins),
      draws: metric(entry.draws),
      losses: metric(entry.losses),
      buchholz: metric(entry.buchholz)
    });
  }
  return cells;
}

/**
 * The public table: the `leaderboard` node with the highest id (or `nodeId`, an aggregate or leaderboard) orders the rows;
 * the aggregate that feeds it supplies one column per input, the cells and the total. A by-role aggregate ranks every
 * role on its own, so a member can hold one row per role: rows are keyed by member and role, and `place` restarts in each.
 * `orderRoles` puts role codes in the game's catalog order (default: first seen).
 */
export function buildLeaderboardTable(
  flow: FlowRead,
  nodeId?: number,
  orderRoles: (codes: Iterable<string>) => string[] = (codes) => [...new Set(codes)]
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
  const byRole = (aggregate?.config as { by_role?: unknown } | undefined)?.by_role === true;

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
  const teamNames = new Map<number, string>();
  for (const p of flow.participants ?? []) {
    if (p.workspace_member_id != null) names.set(`m${p.workspace_member_id}`, p.name);
    else if (p.team_id != null) {
      names.set(`t${p.team_id}`, p.name);
      teamNames.set(p.team_id, p.name);
    }
  }
  // A member's row is told apart by role only when the ranking is by role.
  const rowKey = (r: Result) => (byRole ? `${participantKey(r)}|${roleOf(r) ?? ""}` : participantKey(r));
  const aggregateRows = new Map(
    aggregate ? ranking(flow, aggregate.id).map((r) => [rowKey(r), r]) : []
  );
  const own = ranking(flow, node.id);
  // A tie is 2+ rows sharing a head rank inside one role (every row is role-less when not by role).
  const tieKey = (r: Result) => `${roleOf(r) ?? ""}|${r.tie_group}`;
  const groupSize = new Map<string, number>();
  for (const r of own)
    if (r.tie_group != null) groupSize.set(tieKey(r), (groupSize.get(tieKey(r)) ?? 0) + 1);

  const rows = own.map((r): TableRow => {
    const key = participantKey(r);
    const scored = aggregateRows.get(rowKey(r));
    const cells = breakdownOf(scored);
    const days = columns.map((c) => cells.get(c.nodeId) ?? null);
    return {
      key: rowKey(r),
      role: byRole ? roleOf(r) : null,
      roles: orderRoles(days.flatMap((c) => (c?.role ? [c.role] : []))),
      place: r.tie_group ?? r.rank,
      tied: r.tie_group != null && (groupSize.get(tieKey(r)) ?? 0) > 1,
      name: names.get(key) ?? `#${r.workspace_member_id ?? r.team_id ?? r.stage_item_id}`,
      total: scored?.score ?? r.score,
      cells: days,
      tentative: `${r.state}` !== "final"
    };
  });

  const named = orderRoles(rows.flatMap((r) => (byRole && r.role ? [r.role] : [])));
  return {
    node,
    aggregate,
    columns,
    rows,
    final: rows.length > 0 && rows.every((r) => !r.tentative),
    byRole,
    roles: byRole ? (rows.some((r) => r.role === null) ? [...named, null] : named) : [],
    teamNames
  };
}

export type SortDir = "asc" | "desc";
/** What the table is ordered by: `place`, `name`, `total` or `d<input node id>` for a day column. */
export type SortKey = string;
export type TableView = {
  /** The role tab shown (by-role tables only); null = the "no role" partition. */
  role: string | null;
  query: string;
  sort: SortKey;
  dir: SortDir;
};

export const dayKey = (nodeId: number): SortKey => `d${nodeId}`;
/** Names and places read best first low-to-high; scores best first high-to-low. */
export const firstDir = (key: SortKey): SortDir => (key === "place" || key === "name" ? "asc" : "desc");

/** The `role` query value of the "no role" tab. */
export const NO_ROLE_PARAM = "none";
export const QUERY_MAX_LENGTH = 80;

/** A table view from raw query values; anything unknown falls back to the default (first tab, no search, Place ascending). */
export function parseTableView(
  raw: { role?: string | null; q?: string | null; sort?: string | null; dir?: string | null },
  model: Pick<LeaderboardTableModel, "byRole" | "roles" | "columns">
): TableView {
  const wanted = raw.role === NO_ROLE_PARAM ? null : (raw.role ?? undefined);
  const role = model.byRole
    ? wanted !== undefined && model.roles.includes(wanted)
      ? wanted
      : (model.roles[0] ?? null)
    : null;
  const known =
    raw.sort === "place" ||
    raw.sort === "name" ||
    raw.sort === "total" ||
    model.columns.some((c) => dayKey(c.nodeId) === raw.sort);
  const sort = known ? (raw.sort as SortKey) : "place";
  const dir = raw.dir === "asc" || raw.dir === "desc" ? raw.dir : firstDir(sort);
  return { role, query: (raw.q ?? "").slice(0, QUERY_MAX_LENGTH), sort, dir };
}

/** The query values of a view, null where it equals the default so the URL stays bare. */
export function serializeTableView(
  view: TableView,
  model: Pick<LeaderboardTableModel, "byRole" | "roles" | "columns">
): Record<"role" | "q" | "sort" | "dir", string | null> {
  const dflt = parseTableView({}, model);
  return {
    role: model.byRole && view.role !== dflt.role ? (view.role ?? NO_ROLE_PARAM) : null,
    q: view.query.trim() || null,
    sort: view.sort === "place" ? null : view.sort,
    dir: view.dir === firstDir(view.sort) ? null : view.dir
  };
}

/** Rows whose name (`#tag` included) contains the query, case-insensitively. */
export function filterRows(rows: readonly TableRow[], query: string): TableRow[] {
  const needle = query.trim().toLocaleLowerCase();
  return needle ? rows.filter((r) => r.name.toLocaleLowerCase().includes(needle)) : [...rows];
}

/**
 * The rows ordered by a column. Places are the official ones and never renumbered; a missing cell sorts after every
 * played one in both directions, and equal values keep the leaderboard's order.
 */
export function sortRows(
  rows: readonly TableRow[],
  columns: readonly TableColumn[],
  sort: SortKey,
  dir: SortDir
): TableRow[] {
  const sign = dir === "asc" ? 1 : -1;
  const day = columns.findIndex((c) => dayKey(c.nodeId) === sort);
  const value = (row: TableRow): number | string | null => {
    if (sort === "place") return row.place;
    if (sort === "name") return row.name;
    if (sort === "total") return row.total;
    return row.cells[day]?.score ?? null;
  };
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return sign * (typeof x === "string" ? x.localeCompare(`${y}`) : x - (y as number));
  });
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
