import type { Encounter, EncounterFilters } from "@/types/encounter.types";

export const ENCOUNTERS_PAGE_SIZE = 15;

type EncounterSortKey = "date" | "closeness" | "upcoming";

export type TeamColor = "teal" | "amber" | "rose" | "violet" | "blue";

export type EncounterFilterState = Required<
  Pick<EncounterFilters, "scope">
> & {
  query: string;
  tournament_id: number | null;
  stage_id: number | null;
  stage_item_id: number | null;
  best_of: number | null;
  status: string | null;
  has_logs: boolean | null;
  closeness_min: number | null;
  closeness_max: number | null;
  sort: EncounterSortKey;
};

export const DEFAULT_FILTERS: EncounterFilterState = {
  query: "",
  tournament_id: null,
  stage_id: null,
  stage_item_id: null,
  best_of: null,
  status: null,
  has_logs: null,
  closeness_min: null,
  closeness_max: null,
  scope: "all",
  sort: "date",
};

export type BuiltInViewId = "all" | "my_team" | "finals" | "close_bo5" | "upsets" | "with_logs";

// Translation keys for the built-in view tabs. Kept as a literal union so the
// strictly-typed `t()` in the client accepts `t(view.labelKey)` directly.
type BuiltInViewLabelKey =
  | "encounters.view.all"
  | "encounters.view.myTeam"
  | "encounters.view.finals"
  | "encounters.view.closeBo5"
  | "encounters.view.upsets"
  | "encounters.view.withLogs";

export interface BuiltInViewMeta {
  id: BuiltInViewId;
  labelKey: BuiltInViewLabelKey;
  swatch: TeamColor | null;
  showPin?: boolean;
}

export const BUILT_IN_VIEWS: readonly BuiltInViewMeta[] = [
  { id: "all", labelKey: "encounters.view.all", swatch: "teal" },
  { id: "my_team", labelKey: "encounters.view.myTeam", swatch: null, showPin: true },
  { id: "finals", labelKey: "encounters.view.finals", swatch: "rose" },
  { id: "close_bo5", labelKey: "encounters.view.closeBo5", swatch: "amber" },
  { id: "upsets", labelKey: "encounters.view.upsets", swatch: "violet" },
  { id: "with_logs", labelKey: "encounters.view.withLogs", swatch: "blue" },
] as const;

function parseNumberParam(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseBooleanParam(value: string | undefined): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

export function normalizeEncounterFilters(params: Record<string, string | undefined>): EncounterFilterState {
  const sort = params.sort === "closeness" || params.sort === "upcoming" ? params.sort : "date";
  const scope = params.scope === "my_team" ? "my_team" : "all";

  return {
    query: params.search ?? params.query ?? "",
    tournament_id: parseNumberParam(params.tournament_id),
    stage_id: parseNumberParam(params.stage_id),
    stage_item_id: parseNumberParam(params.stage_item_id),
    best_of: parseNumberParam(params.best_of),
    status: params.status || null,
    has_logs: parseBooleanParam(params.has_logs),
    closeness_min: parseNumberParam(params.closeness_min) ?? DEFAULT_FILTERS.closeness_min,
    closeness_max: parseNumberParam(params.closeness_max),
    scope,
    sort,
  };
}

export function filtersToSearchParams(filters: EncounterFilterState, page: number): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.query) params.set("search", filters.query);
  if (page > 1) params.set("page", String(page));
  if (filters.tournament_id != null) params.set("tournament_id", String(filters.tournament_id));
  if (filters.stage_id != null) params.set("stage_id", String(filters.stage_id));
  if (filters.stage_item_id != null) params.set("stage_item_id", String(filters.stage_item_id));
  if (filters.best_of != null) params.set("best_of", String(filters.best_of));
  if (filters.status) params.set("status", filters.status);
  if (filters.has_logs != null) params.set("has_logs", String(filters.has_logs));
  if (filters.closeness_min != null && filters.closeness_min !== DEFAULT_FILTERS.closeness_min) {
    params.set("closeness_min", String(filters.closeness_min));
  }
  if (filters.closeness_max != null) params.set("closeness_max", String(filters.closeness_max));
  if (filters.scope !== "all") params.set("scope", filters.scope);
  if (filters.sort !== "date") params.set("sort", filters.sort);
  return params;
}

export function filtersToApiFilters(filters: EncounterFilterState): EncounterFilters {
  return {
    tournament_id: filters.tournament_id,
    stage_id: filters.stage_id,
    stage_item_id: filters.stage_item_id,
    best_of: filters.best_of,
    status: filters.status,
    has_logs: filters.has_logs,
    closeness_min: filters.closeness_min,
    closeness_max: filters.closeness_max,
    scope: filters.scope,
    sort: filters.sort === "closeness" ? "closeness" : filters.sort === "upcoming" ? "scheduled_at" : "id",
  };
}

export function applyBuiltInView(viewId: string, filters: EncounterFilterState): EncounterFilterState {
  switch (viewId) {
    case "my_team":
      return { ...filters, scope: "my_team" };
    case "finals":
      return { ...filters, stage_id: null, stage_item_id: null, status: "completed" };
    case "close_bo5":
      return { ...filters, best_of: 5, closeness_min: 0.6 };
    case "with_logs":
      return { ...filters, has_logs: true };
    case "upsets":
      return { ...filters, status: "completed", sort: "closeness" };
    default:
      return { ...DEFAULT_FILTERS, query: filters.query };
  }
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "-";
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export function formatPercent(value: number | null | undefined, fallback = "-"): string {
  if (value == null || Number.isNaN(value)) return fallback;
  return `${Math.round(value)}%`;
}

export function getSeriesDuration(encounter: Encounter): number {
  return encounter.matches?.reduce((sum, match) => sum + (match.time || 0), 0) ?? 0;
}
