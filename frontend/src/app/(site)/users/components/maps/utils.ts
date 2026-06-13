export const PAGE_KEY = "mapsPage";
export const PER_PAGE_KEY = "mapsPerPage";
export const QUERY_KEY = "mapsQuery";
export const MIN_COUNT_KEY = "mapsMinCount";
export const SORT_KEY = "mapsSort";
export const ORDER_KEY = "mapsOrder";

export type SortKey = "winrate" | "count" | "name";
export type OrderKey = "asc" | "desc";

export const clampInt = (value: string | null, fallback: number, min: number, max: number) => {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
};

export const parsePerPage = (value: string | null) => {
  if (!value) return -1;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return -1;
  if (parsed === -1) return -1;
  if (parsed === 15 || parsed === 30) return parsed;
  return -1;
};

export const formatPercent = (value: number, digits = 0) => `${(value * 100).toFixed(digits)}%`;

export const formatSeconds = (secondsRaw: number) => {
  const seconds = Math.max(0, Math.floor(secondsRaw));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};
