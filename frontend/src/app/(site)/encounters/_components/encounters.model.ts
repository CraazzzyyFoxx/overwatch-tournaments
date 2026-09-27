import type { Formatter } from "@/lib/datetime";
import type {
  EncounterSavedView,
  EncounterScoreHeatmapCell,
  EncounterStageSplit
} from "@/types/encounter.types";
import {
  DEFAULT_FILTERS,
  type BuiltInViewId,
  type EncounterFilterState,
  type TeamColor
} from "./encounters.helpers";

/** Only `number` is needed here; `useFormatter()` and `await getFormatter()` both satisfy it. */
export type NumberFormatter = Pick<Formatter, "number">;

export const VIEW_SWATCH_COLOR: Record<TeamColor, string> = {
  teal: "var(--aqt-teal)",
  amber: "var(--aqt-amber)",
  rose: "var(--aqt-rose)",
  violet: "var(--aqt-violet)",
  blue: "var(--aqt-blue)"
};

const STAGE_DONUT_COLORS = [
  "var(--aqt-blue)",
  "var(--aqt-amber)",
  "var(--aqt-rose)",
  "var(--aqt-teal)",
  "var(--aqt-violet)"
];

/** Locale-aware count, or a dash when the overview reported none. */
export function countLabel(format: NumberFormatter, value?: number): string {
  return typeof value === "number" ? format.number(value) : "-";
}

export function selectedViewId(filters: EncounterFilterState): BuiltInViewId {
  if (filters.scope === "my_team") return "my_team";
  if (filters.best_of === 5 && filters.closeness_min === 0.6) return "close_bo5";
  if (filters.has_logs === true) return "with_logs";
  if (filters.status === "completed" && filters.sort === "closeness") return "upsets";
  if (filters.status === "completed") return "finals";
  return "all";
}

export function toSavedFilterState(view: EncounterSavedView): EncounterFilterState {
  return {
    ...DEFAULT_FILTERS,
    ...view.filters,
    query: view.filters.query ?? "",
    sort:
      view.filters.sort === "closeness" || view.filters.sort === "upcoming"
        ? view.filters.sort
        : DEFAULT_FILTERS.sort,
    scope: view.filters.scope === "my_team" ? "my_team" : "all"
  };
}

/** True once anything narrows the list — drives the "clear filters" empty state. */
export function hasActiveFilters(filters: EncounterFilterState): boolean {
  return (
    filters.query !== "" ||
    filters.status != null ||
    filters.has_logs != null ||
    filters.tournament_id != null ||
    filters.stage_id != null ||
    filters.stage_item_id != null ||
    filters.best_of != null ||
    filters.closeness_min != null ||
    filters.closeness_max != null ||
    filters.scope !== DEFAULT_FILTERS.scope ||
    filters.sort !== DEFAULT_FILTERS.sort
  );
}

export function buildHeatmapMatrix(cells: EncounterScoreHeatmapCell[]) {
  const matrix: Record<string, number> = {};
  let max = 0;
  for (const cell of cells) {
    matrix[`${cell.home}-${cell.away}`] = cell.count;
    if (cell.count > max) max = cell.count;
  }
  const rows = [3, 2, 1, 0];
  const cols = [0, 1, 2, 3];
  return { matrix, rows, cols, max };
}

export function donutSegments(stages: EncounterStageSplit[]) {
  const total = stages.reduce((sum, stage) => sum + stage.count, 0);
  if (total === 0) return { segments: [], total: 0 };
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = stages.slice(0, 5).map((stage, index) => {
    const fraction = stage.count / total;
    const length = fraction * circumference;
    const segment = {
      name: stage.name,
      count: stage.count,
      pct: stage.pct,
      color: STAGE_DONUT_COLORS[index % STAGE_DONUT_COLORS.length],
      dashArray: `${length.toFixed(2)} ${circumference.toFixed(2)}`,
      dashOffset: -offset
    };
    offset += length;
    return segment;
  });
  return { segments, total, circumference, radius };
}
