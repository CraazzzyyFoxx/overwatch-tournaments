export const PARTICIPANT_SEARCH_PARAM = "participantSearch";
export const PARTICIPANT_STATUS_PARAM = "participantStatus";
export const PARTICIPANT_COLUMNS_PARAM = "participantColumns";

export const PARTICIPANT_SEARCH_MAX_LENGTH = 120;
export const PARTICIPANT_MANDATORY_COLUMN_IDS = ["battle_tag", "_status"] as const;

const PARTICIPANT_MANDATORY_COLUMN_ID_SET = new Set<string>(
  PARTICIPANT_MANDATORY_COLUMN_IDS,
);

export function isMandatoryParticipantColumnId(columnId: string): boolean {
  return PARTICIPANT_MANDATORY_COLUMN_ID_SET.has(columnId);
}

interface ParticipantColumnOption {
  id: string;
  defaultVisible: boolean;
}

/**
 * Canonical "Reset to defaults" column set: mandatory columns first, then
 * every optional column flagged `defaultVisible`, in column order. Both the
 * initial page load (no URL param, no stored selection) and the Reset button
 * derive from this single helper, so they can never disagree.
 */
export function participantDefaultColumnIds(
  columns: readonly ParticipantColumnOption[],
): string[] {
  return [
    ...columns
      .filter((column) => isMandatoryParticipantColumnId(column.id))
      .map((column) => column.id),
    ...columns
      .filter(
        (column) =>
          !isMandatoryParticipantColumnId(column.id) && column.defaultVisible,
      )
      .map((column) => column.id),
  ];
}

// ---------------------------------------------------------------------------
// Column selection persistence (localStorage)
//
// The column selection lives in the URL for sharing/back-forward, but tab
// navigation inside a tournament drops query params. The optional column ids
// are therefore mirrored per tournament in localStorage: an explicit URL param
// always wins, the stored selection seeds the state when the param is absent,
// and Reset clears the stored entry.
// ---------------------------------------------------------------------------

type ColumnStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function participantColumnsStorageKey(tournamentId: number): string {
  return `aqt:participants:columns:v1:${tournamentId}`;
}

/**
 * Parses a raw stored value into optional column ids, or `null` when nothing
 * valid is stored. An empty array means "no optional columns" (explicit
 * "none").
 */
export function parseStoredParticipantColumnIds(raw: string | null): string[] | null {
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || !parsed.every((id) => typeof id === "string")) {
      return null;
    }
    return parsed.filter((id) => !isMandatoryParticipantColumnId(id));
  } catch {
    return null;
  }
}

/** Stored optional column ids for the tournament; see `parseStoredParticipantColumnIds`. */
export function readStoredParticipantColumnIds(
  storage: ColumnStorage | null,
  tournamentId: number,
): string[] | null {
  if (!storage) return null;
  try {
    return parseStoredParticipantColumnIds(
      storage.getItem(participantColumnsStorageKey(tournamentId)),
    );
  } catch {
    return null;
  }
}

// Same-tab writes never fire the browser `storage` event, so writers notify
// these listeners; `useSyncExternalStore` in the page subscribes to both.
const columnStorageListeners = new Set<() => void>();

function emitParticipantColumnsStorageChange(): void {
  for (const listener of columnStorageListeners) listener();
}

export function subscribeParticipantColumnsStorage(listener: () => void): () => void {
  columnStorageListeners.add(listener);
  if (typeof window !== "undefined") {
    window.addEventListener("storage", listener);
  }
  return () => {
    columnStorageListeners.delete(listener);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", listener);
    }
  };
}

/**
 * Persists the visible column selection. The default selection removes the
 * entry (nothing stored = defaults), everything else stores the optional ids.
 * Returns the stored optional ids, or `null` when the entry was removed.
 */
export function writeStoredParticipantColumnIds(
  storage: ColumnStorage | null,
  tournamentId: number,
  visibleColumnIds: readonly string[],
  defaultColumnIds: readonly string[],
): string[] | null {
  const optionalValue = visibleColumnIds.filter(
    (id) => !isMandatoryParticipantColumnId(id),
  );
  const optionalDefaultValue = defaultColumnIds.filter(
    (id) => !isMandatoryParticipantColumnId(id),
  );
  const isDefault = sameValues(optionalValue, optionalDefaultValue);
  try {
    if (!storage) return isDefault ? null : optionalValue;
    const key = participantColumnsStorageKey(tournamentId);
    if (isDefault) {
      storage.removeItem(key);
    } else {
      storage.setItem(key, JSON.stringify(optionalValue));
    }
    emitParticipantColumnsStorageChange();
    return isDefault ? null : optionalValue;
  } catch {
    return isDefault ? null : optionalValue;
  }
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

interface ParticipantResultsTransitionContext {
  search: string;
  status: string;
  visibleColumnIds: readonly string[];
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

export function participantResultsTransitionSignature({
  search,
  status,
  visibleColumnIds,
}: ParticipantResultsTransitionContext): string {
  return `${status}|${search}|${visibleColumnIds.join(",")}`;
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
  const optionalValue = value.filter((id) => !isMandatoryParticipantColumnId(id));
  const optionalDefaultValue = defaultValue.filter(
    (id) => !isMandatoryParticipantColumnId(id),
  );
  if (sameValues(optionalValue, optionalDefaultValue)) {
    params.delete(PARTICIPANT_COLUMNS_PARAM);
    return;
  }

  params.set(
    PARTICIPANT_COLUMNS_PARAM,
    optionalValue.length > 0 ? optionalValue.join(",") : "none",
  );
}

export function readParticipantUrlState(
  source: URLSearchParams,
  allowedStatuses: readonly string[],
  columns: readonly ParticipantColumnOption[],
  storedColumnIds: readonly string[] | null = null,
): ParticipantUrlReadResult {
  const original = source.toString();
  const params = new URLSearchParams(original);
  const search = writeSearch(params, source.get(PARTICIPANT_SEARCH_PARAM) ?? "");

  const rawStatus = source.get(PARTICIPANT_STATUS_PARAM) ?? "all";
  const status =
    rawStatus === "all" || allowedStatuses.includes(rawStatus) ? rawStatus : "all";
  writeStatus(params, status);

  const mandatoryColumnIds = columns
    .filter((column) => isMandatoryParticipantColumnId(column.id))
    .map((column) => column.id);
  const optionalColumns = columns.filter(
    (column) => !isMandatoryParticipantColumnId(column.id),
  );
  const defaultColumnIds = participantDefaultColumnIds(columns);
  const allowedOptionalColumnIds = new Set(optionalColumns.map((column) => column.id));
  const rawColumns = source.get(PARTICIPANT_COLUMNS_PARAM);
  let visibleColumnIds = defaultColumnIds;

  if (rawColumns === "none") {
    visibleColumnIds = mandatoryColumnIds;
  } else if (rawColumns !== null) {
    const rawColumnIds = rawColumns.split(",").filter(Boolean);
    const requested = new Set(
      rawColumnIds.filter((id) => allowedOptionalColumnIds.has(id)),
    );
    const isLegacyCoreOnly =
      rawColumnIds.length > 0 &&
      rawColumnIds.every((id) => isMandatoryParticipantColumnId(id));
    if (requested.size > 0 || isLegacyCoreOnly) {
      visibleColumnIds = [
        ...mandatoryColumnIds,
        ...optionalColumns
          .filter((column) => requested.has(column.id))
          .map((column) => column.id),
      ];
    }
  }

  // URL normalization is computed from URL-owned state only, BEFORE the
  // stored selection applies — restoring a persisted selection must not spray
  // it back into the address bar.
  writeColumns(params, visibleColumnIds, defaultColumnIds);

  if (rawColumns === null && storedColumnIds !== null) {
    const requested = new Set(
      storedColumnIds.filter((id) => allowedOptionalColumnIds.has(id)),
    );
    if (storedColumnIds.length === 0) {
      visibleColumnIds = mandatoryColumnIds;
    } else if (requested.size > 0) {
      visibleColumnIds = [
        ...mandatoryColumnIds,
        ...optionalColumns
          .filter((column) => requested.has(column.id))
          .map((column) => column.id),
      ];
    }
  }

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
