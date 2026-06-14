import type { Encounter, EncounterFilters } from "@/types/encounter.types";

export const ENCOUNTERS_PAGE_SIZE = 15;

export type EncounterSortKey = "date" | "closeness" | "upcoming";

export type TeamColor = "teal" | "amber" | "rose" | "violet" | "blue";

const TEAM_COLOR_PALETTE: TeamColor[] = ["teal", "amber", "rose", "violet", "blue"];

export function getTeamColor(name: string | null | undefined): TeamColor {
  if (!name) return "teal";
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % TEAM_COLOR_PALETTE.length;
  return TEAM_COLOR_PALETTE[index];
}

export type StageBucket = "playoffs" | "group" | "finals" | "default";

export function getStageBucket(stageName: string | null | undefined): StageBucket {
  if (!stageName) return "default";
  const lower = stageName.toLowerCase();
  if (lower.includes("final") || lower.includes("grand")) return "finals";
  if (lower.includes("playoff") || lower.includes("bracket") || lower.includes("knockout")) {
    return "playoffs";
  }
  if (lower.includes("group") || lower.includes("swiss") || lower.includes("round robin")) {
    return "group";
  }
  return "default";
}

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

export interface BuiltInViewMeta {
  id: BuiltInViewId;
  label: string;
  swatch: TeamColor | null;
  showPin?: boolean;
}

export const BUILT_IN_VIEWS: readonly BuiltInViewMeta[] = [
  { id: "all", label: "All encounters", swatch: "teal" },
  { id: "my_team", label: "My team's series", swatch: null, showPin: true },
  { id: "finals", label: "Finals only", swatch: "rose" },
  { id: "close_bo5", label: "Close Bo5s", swatch: "amber" },
  { id: "upsets", label: "Upsets", swatch: "violet" },
  { id: "with_logs", label: "With logs", swatch: "blue" },
] as const;

export function buildPageList(currentPage: number, totalPages: number): Array<number | "ellipsis"> {
  if (totalPages <= 1) return [1];
  const pages = new Set<number>([1, totalPages, currentPage, currentPage - 1, currentPage + 1]);
  const sorted = Array.from(pages)
    .filter((value) => value >= 1 && value <= totalPages)
    .sort((a, b) => a - b);
  const result: Array<number | "ellipsis"> = [];
  for (let i = 0; i < sorted.length; i += 1) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) result.push("ellipsis");
    result.push(sorted[i]);
  }
  return result;
}

export function parseNumberParam(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function parseBooleanParam(value: string | undefined): boolean | null {
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

export function getPlayedAt(encounter: Encounter): string | Date | null {
  return (
    encounter.confirmed_at ??
    encounter.ended_at ??
    encounter.updated_at ??
    encounter.created_at ??
    null
  );
}

export function getEncounterStateLabel(encounter: Encounter, now = new Date()): string {
  const scheduledAt = encounter.scheduled_at ? new Date(encounter.scheduled_at) : null;
  if (encounter.started_at && !encounter.ended_at) return "Live";
  if (scheduledAt && scheduledAt.getTime() > now.getTime()) return "Upcoming";
  if (encounter.status === "completed") return "Final";
  if (encounter.status === "pending") return "Pending";
  return "Open";
}

export function formatCompactDate(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
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

export function getTeamInitials(name: string | null | undefined): string {
  if (!name) return "--";
  const words = name.trim().split(/\s+/);
  const value = words.length > 1 ? `${words[0][0]}${words[1][0]}` : name.slice(0, 2);
  return value.toUpperCase();
}

export function getWinnerSide(encounter: Encounter): "home" | "away" | null {
  if (encounter.score.home > encounter.score.away) return "home";
  if (encounter.score.away > encounter.score.home) return "away";
  return null;
}

export type MediaSlotKey = "logs" | "vod" | "cast";

export interface MediaSlot {
  key: MediaSlotKey;
  label: string;
  enabled: boolean;
}

export function getMediaSlots(hasLogs: boolean): MediaSlot[] {
  return [
    { key: "logs", label: hasLogs ? "Game logs available" : "No game logs", enabled: hasLogs },
    { key: "vod", label: "Coming with Twitch integration", enabled: false },
    { key: "cast", label: "Coming with Twitch integration", enabled: false },
  ];
}
