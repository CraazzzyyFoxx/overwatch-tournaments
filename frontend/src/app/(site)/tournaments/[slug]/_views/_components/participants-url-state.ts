// Public URL contract for this section (redesign plan §1.2): `q` for search,
// `view` for the pool/table switch. `participantStatus`/`participantColumns`
// keep their prefixed names — they are table-only knobs with no counterpart on
// the other public sections.
const PARTICIPANT_SEARCH_PARAM = "q";
const PARTICIPANT_STATUS_PARAM = "participantStatus";
const PARTICIPANT_COLUMNS_PARAM = "participantColumns";
const PARTICIPANT_VIEW_PARAM = "view";
const PARTICIPANT_DIVISION_PARAM = "division";

/** The two shapes the roster renders in; `pool` exists only for balancer/draft. */
export type ParticipantView = "pool" | "table";

export const PARTICIPANT_VIEWS: readonly ParticipantView[] = ["pool", "table"];

function isParticipantView(value: string | null): value is ParticipantView {
  return value === "pool" || value === "table";
}

export const PARTICIPANT_SEARCH_MAX_LENGTH = 120;
const PARTICIPANT_MANDATORY_COLUMN_IDS = ["identity_battlenet", "_status"] as const;

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

type PageStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

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
  storage: PageStorage | null,
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
  storage: PageStorage | null,
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

// ---------------------------------------------------------------------------
// One-shot check-in prompt (localStorage)
//
// Check-in is the only deadline on this page, and the player who misses it is
// the one who never scrolled down to the card. So the first visit while the
// window is open opens the dialog itself — once per tournament per browser,
// because a prompt that returns on every reload is a nag and trains the reflex
// to dismiss it.
// ---------------------------------------------------------------------------

function checkInPromptStorageKey(tournamentId: number): string {
  return `aqt:participants:checkin-prompted:v1:${tournamentId}`;
}

/**
 * Whether this browser should auto-open the check-in dialog, claiming the
 * one-shot when it says yes so the next call returns `false`.
 *
 * Unreadable storage (private mode, blocked cookies) answers `true`: the
 * prompt then repeats once per mount, which is the failure this page prefers
 * over silently never reminding anyone.
 */
export function claimCheckInPrompt(
  storage: PageStorage | null,
  tournamentId: number,
): boolean {
  if (!storage) return true;
  try {
    const key = checkInPromptStorageKey(tournamentId);
    if (storage.getItem(key) !== null) return false;
    storage.setItem(key, "1");
    return true;
  } catch {
    return true;
  }
}

interface ParticipantUrlState {
  search: string;
  status: string;
  visibleColumnIds: string[];
  view: ParticipantView;
  /** Division number the pool is narrowed to; `null` = every division. */
  division: number | null;
}

export interface ParticipantUrlReadResult {
  state: ParticipantUrlState;
  params: URLSearchParams;
  needsNormalization: boolean;
}

export type ParticipantUrlUpdate =
  | { type: "search"; value: string }
  | { type: "status"; value: string }
  | { type: "division"; value: number | null }
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
  division?: number | null;
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
  division = null,
  visibleColumnIds,
}: ParticipantResultsTransitionContext): string {
  return `${status}|${division ?? "all"}|${search}|${visibleColumnIds.join(",")}`;
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

/** `null` (and any non-positive/garbage value) means "every division". */
function writeDivision(params: URLSearchParams, value: number | null): number | null {
  if (value === null) {
    params.delete(PARTICIPANT_DIVISION_PARAM);
    return null;
  }
  params.set(PARTICIPANT_DIVISION_PARAM, String(value));
  return value;
}

function parseDivision(raw: string | null): number | null {
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/** The default view is never written, so a bare URL means "the default". */
function writeView(
  params: URLSearchParams,
  value: ParticipantView,
  defaultValue: ParticipantView,
): void {
  if (value === defaultValue) params.delete(PARTICIPANT_VIEW_PARAM);
  else params.set(PARTICIPANT_VIEW_PARAM, value);
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
  /** `pool` for balancer/draft tournaments, `table` everywhere else. */
  defaultView: ParticipantView = "table",
): ParticipantUrlReadResult {
  const original = source.toString();
  const params = new URLSearchParams(original);
  const search = writeSearch(params, source.get(PARTICIPANT_SEARCH_PARAM) ?? "");

  const rawStatus = source.get(PARTICIPANT_STATUS_PARAM) ?? "all";
  const status =
    rawStatus === "all" || allowedStatuses.includes(rawStatus) ? rawStatus : "all";
  writeStatus(params, status);

  const rawView = source.get(PARTICIPANT_VIEW_PARAM);
  const view = isParticipantView(rawView) ? rawView : defaultView;
  writeView(params, view, defaultView);

  const division = writeDivision(params, parseDivision(source.get(PARTICIPANT_DIVISION_PARAM)));

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
    state: { search, status, visibleColumnIds, view, division },
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
    case "division":
      writeDivision(params, update.value);
      return { params, history: "push" };
    case "columns":
      writeColumns(params, update.value, update.defaultValue);
      return { params, history: "push" };
    case "reset":
      params.delete(PARTICIPANT_SEARCH_PARAM);
      params.delete(PARTICIPANT_STATUS_PARAM);
      params.delete(PARTICIPANT_COLUMNS_PARAM);
      params.delete(PARTICIPANT_DIVISION_PARAM);
      return { params, history: "push" };
  }
}
