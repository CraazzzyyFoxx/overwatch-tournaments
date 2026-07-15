export const PARTICIPANT_SEARCH_PARAM = "participantSearch";
export const PARTICIPANT_STATUS_PARAM = "participantStatus";
export const PARTICIPANT_COLUMNS_PARAM = "participantColumns";

export const PARTICIPANT_SEARCH_MAX_LENGTH = 120;

interface ParticipantColumnOption {
  id: string;
  defaultVisible: boolean;
}

export interface ParticipantUrlState {
  search: string;
  status: string;
  visibleColumnIds: string[];
}

export interface ParticipantUrlReadResult {
  state: ParticipantUrlState;
  params: URLSearchParams;
  needsNormalization: boolean;
}

export type ParticipantUrlUpdate =
  | { type: "search"; value: string }
  | { type: "status"; value: string }
  | { type: "columns"; value: string[]; defaultValue: string[] }
  | { type: "reset" };

export interface ParticipantUrlUpdateResult {
  params: URLSearchParams;
  history: "push" | "replace";
}

interface ParticipantResultsScrollContext {
  scrollY: number;
  headingDocumentTop: number;
  stickyOffset: number;
}

export function normalizeParticipantSearch(value: string): string {
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, "")
    .trim()
    .slice(0, PARTICIPANT_SEARCH_MAX_LENGTH);
}

export function shouldScrollParticipantResults({
  scrollY,
  headingDocumentTop,
  stickyOffset,
}: ParticipantResultsScrollContext): boolean {
  return scrollY + stickyOffset > headingDocumentTop;
}

export function participantResultsScrollTarget(
  headingDocumentTop: number,
  stickyOffset: number,
): number {
  return Math.max(0, headingDocumentTop - stickyOffset - 12);
}

function sameValues(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function writeSearch(params: URLSearchParams, value: string): string {
  const normalized = normalizeParticipantSearch(value);
  if (normalized) params.set(PARTICIPANT_SEARCH_PARAM, normalized);
  else params.delete(PARTICIPANT_SEARCH_PARAM);
  return normalized;
}

function writeStatus(params: URLSearchParams, value: string): string {
  if (value && value !== "all") params.set(PARTICIPANT_STATUS_PARAM, value);
  else params.delete(PARTICIPANT_STATUS_PARAM);
  return value || "all";
}

function writeColumns(
  params: URLSearchParams,
  value: readonly string[],
  defaultValue: readonly string[],
): void {
  if (sameValues(value, defaultValue)) {
    params.delete(PARTICIPANT_COLUMNS_PARAM);
    return;
  }

  params.set(PARTICIPANT_COLUMNS_PARAM, value.length > 0 ? value.join(",") : "none");
}

export function readParticipantUrlState(
  source: URLSearchParams,
  allowedStatuses: readonly string[],
  columns: readonly ParticipantColumnOption[],
): ParticipantUrlReadResult {
  const original = source.toString();
  const params = new URLSearchParams(original);
  const search = writeSearch(params, source.get(PARTICIPANT_SEARCH_PARAM) ?? "");

  const rawStatus = source.get(PARTICIPANT_STATUS_PARAM) ?? "all";
  const status =
    rawStatus === "all" || allowedStatuses.includes(rawStatus) ? rawStatus : "all";
  writeStatus(params, status);

  const defaultColumnIds = columns.filter((column) => column.defaultVisible).map((column) => column.id);
  const allowedColumnIds = new Set(columns.map((column) => column.id));
  const rawColumns = source.get(PARTICIPANT_COLUMNS_PARAM);
  let visibleColumnIds = defaultColumnIds;

  if (rawColumns === "none") {
    visibleColumnIds = [];
  } else if (rawColumns !== null) {
    const requested = new Set(rawColumns.split(",").filter((id) => allowedColumnIds.has(id)));
    visibleColumnIds = columns.filter((column) => requested.has(column.id)).map((column) => column.id);
    if (visibleColumnIds.length === 0) visibleColumnIds = defaultColumnIds;
  }

  writeColumns(params, visibleColumnIds, defaultColumnIds);

  return {
    state: { search, status, visibleColumnIds },
    params,
    needsNormalization: params.toString() !== original,
  };
}

export function updateParticipantUrlState(
  source: URLSearchParams,
  update: ParticipantUrlUpdate,
): ParticipantUrlUpdateResult {
  const params = new URLSearchParams(source.toString());

  switch (update.type) {
    case "search":
      writeSearch(params, update.value);
      return { params, history: "replace" };
    case "status":
      writeStatus(params, update.value);
      return { params, history: "push" };
    case "columns":
      writeColumns(params, update.value, update.defaultValue);
      return { params, history: "push" };
    case "reset":
      params.delete(PARTICIPANT_SEARCH_PARAM);
      params.delete(PARTICIPANT_STATUS_PARAM);
      params.delete(PARTICIPANT_COLUMNS_PARAM);
      return { params, history: "push" };
  }
}
