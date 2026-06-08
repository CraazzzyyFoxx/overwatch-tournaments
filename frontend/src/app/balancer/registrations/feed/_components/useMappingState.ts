"use client";

import { useCallback, useRef, useState } from "react";

import type {
  AdminGoogleSheetFeed,
  MappingCatalog,
  MappingTargetMode,
  MappingTargetState,
  MappingValueCategoryName,
  ValueMapRow,
  ValueMappingState,
} from "@/types/balancer-admin.types";

// ---------------------------------------------------------------------------
// Parsing of the persisted mapping_config_json / value_mapping_json shapes
// ---------------------------------------------------------------------------

interface PersistedTargetEntry {
  mode?: string;
  columns?: unknown;
  value?: unknown;
  parser?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

let rowSeq = 0;
function nextRowId(): string {
  rowSeq += 1;
  return `vm-${rowSeq}`;
}

function entriesToRows(entries: Record<string, unknown> | undefined): ValueMapRow[] {
  if (!isRecord(entries)) {
    return [];
  }
  return Object.entries(entries).map(([key, value]) => ({
    id: nextRowId(),
    key,
    value: typeof value === "boolean" ? String(value) : value == null ? "" : String(value),
  }));
}

function roleSubroleEntriesToRows(entries: Record<string, unknown> | undefined): ValueMapRow[] {
  if (!isRecord(entries)) return [];
  return Object.entries(entries).map(([key, value]) => ({
    id: nextRowId(),
    key,
    value: isRecord(value) ? JSON.stringify(value) : "",
  }));
}

function buildInitialMappingState(
  catalog: MappingCatalog,
  feed: AdminGoogleSheetFeed | null,
): Record<string, MappingTargetState> {
  const persistedTargets = isRecord(feed?.mapping_config_json?.targets)
    ? (feed?.mapping_config_json?.targets as Record<string, PersistedTargetEntry>)
    : {};

  const state: Record<string, MappingTargetState> = {};

  for (const target of catalog.targets) {
    const persisted = persistedTargets[target.key];
    if (!persisted) {
      // Not configured yet: disabled by default, parser seeded from the catalog.
      state[target.key] = {
        mode: "disabled",
        columns: [],
        value: "",
        parser: target.default_parser,
      };
      continue;
    }

    const mode: MappingTargetMode =
      persisted.mode === "constant"
        ? "constant"
        : persisted.mode === "disabled"
          ? "disabled"
          : "columns";

    const parser =
      typeof persisted.parser === "string" && persisted.parser.length > 0
        ? persisted.parser
        : target.default_parser;

    state[target.key] = {
      mode,
      columns: toStringArray(persisted.columns),
      value: typeof persisted.value === "string" ? persisted.value : persisted.value == null ? "" : String(persisted.value),
      parser,
    };
  }

  return state;
}

function buildInitialValueState(feed: AdminGoogleSheetFeed | null): ValueMappingState {
  const raw = isRecord(feed?.value_mapping_json) ? feed?.value_mapping_json : undefined;
  return {
    booleans: entriesToRows(isRecord(raw?.booleans) ? (raw?.booleans as Record<string, unknown>) : undefined),
    roles: entriesToRows(isRecord(raw?.roles) ? (raw?.roles as Record<string, unknown>) : undefined),
    subroles: entriesToRows(isRecord(raw?.subroles) ? (raw?.subroles as Record<string, unknown>) : undefined),
    role_subroles: roleSubroleEntriesToRows(isRecord(raw?.role_subroles) ? (raw?.role_subroles as Record<string, unknown>) : undefined),
    divisions: entriesToRows(isRecord(raw?.divisions) ? (raw?.divisions as Record<string, unknown>) : undefined),
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const EMPTY_VALUE_STATE: ValueMappingState = { booleans: [], roles: [], subroles: [], role_subroles: [], divisions: [] };

export interface UseMappingStateResult {
  mappingState: Record<string, MappingTargetState>;
  valueState: ValueMappingState;
  hasChanges: boolean;
  isHydrated: boolean;
  hydrate: (catalog: MappingCatalog, feed: AdminGoogleSheetFeed | null, scopeKey?: string) => void;
  applySuggestedMapping: (mappingConfigJson: Record<string, unknown> | null | undefined) => void;
  resetChanges: () => void;
  setTargetMode: (key: string, mode: MappingTargetMode) => void;
  setTargetColumns: (key: string, columns: string[]) => void;
  setTargetValue: (key: string, value: string) => void;
  setTargetParser: (key: string, parser: string) => void;
  addValueRow: (category: MappingValueCategoryName) => void;
  updateValueRow: (category: MappingValueCategoryName, id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
  removeValueRow: (category: MappingValueCategoryName, id: string) => void;
  seedValueDefaults: (category: MappingValueCategoryName, entries: Record<string, unknown>) => void;
}

/**
 * Holds the mapper editor state. `hydrate` runs once per feed id (guarded by a
 * ref like the form builder) so a background refetch never clobbers edits.
 */
export function useMappingState(): UseMappingStateResult {
  const [mappingState, setMappingState] = useState<Record<string, MappingTargetState>>({});
  const [valueState, setValueState] = useState<ValueMappingState>(EMPTY_VALUE_STATE);
  const [hasChanges, setHasChanges] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);

  // null feed still hydrates (empty defaults); a sentinel distinguishes "new".
  const loadedFeedIdRef = useRef<string | null>(null);

  const hydrate = useCallback((catalog: MappingCatalog, feed: AdminGoogleSheetFeed | null, scopeKey = "") => {
    const feedKey = `${scopeKey}:${feed ? String(feed.id) : "__none__"}`;
    setHasChanges((currentlyDirty) => {
      if (loadedFeedIdRef.current === feedKey && currentlyDirty) {
        // Same feed, unsaved edits in flight — don't clobber.
        return currentlyDirty;
      }
      loadedFeedIdRef.current = feedKey;
      setMappingState(buildInitialMappingState(catalog, feed));
      setValueState(buildInitialValueState(feed));
      setIsHydrated(true);
      return false;
    });
  }, []);

  const applySuggestedMapping = useCallback((mappingConfigJson: Record<string, unknown> | null | undefined) => {
    const targets =
      isRecord(mappingConfigJson) && isRecord(mappingConfigJson.targets)
        ? (mappingConfigJson.targets as Record<string, PersistedTargetEntry>)
        : {};
    setMappingState((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const [key, entry] of Object.entries(targets)) {
        const current = next[key];
        // Skip unknown targets (not in the catalog) and non-column suggestions.
        if (!current || !entry || entry.mode !== "columns") {
          continue;
        }
        const columns = toStringArray(entry.columns);
        if (columns.length === 0) {
          continue;
        }
        // Suggestions are a starting point — never clobber an existing mapping.
        if (current.mode === "columns" && current.columns.length > 0) {
          continue;
        }
        next[key] = {
          ...current,
          mode: "columns",
          columns,
          parser: typeof entry.parser === "string" && entry.parser.length > 0 ? entry.parser : current.parser,
        };
        changed = true;
      }
      return changed ? next : prev;
    });
    setHasChanges(true);
  }, []);

  const resetChanges = useCallback(() => setHasChanges(false), []);

  const setTargetMode = useCallback((key: string, mode: MappingTargetMode) => {
    setMappingState((prev) => {
      const current = prev[key];
      if (!current || current.mode === mode) {
        return prev;
      }
      return { ...prev, [key]: { ...current, mode } };
    });
    setHasChanges(true);
  }, []);

  const setTargetColumns = useCallback((key: string, columns: string[]) => {
    setMappingState((prev) => {
      const current = prev[key];
      if (!current) {
        return prev;
      }
      return { ...prev, [key]: { ...current, columns } };
    });
    setHasChanges(true);
  }, []);

  const setTargetValue = useCallback((key: string, value: string) => {
    setMappingState((prev) => {
      const current = prev[key];
      if (!current) {
        return prev;
      }
      return { ...prev, [key]: { ...current, value } };
    });
    setHasChanges(true);
  }, []);

  const setTargetParser = useCallback((key: string, parser: string) => {
    setMappingState((prev) => {
      const current = prev[key];
      if (!current) {
        return prev;
      }
      return { ...prev, [key]: { ...current, parser } };
    });
    setHasChanges(true);
  }, []);

  const addValueRow = useCallback((category: MappingValueCategoryName) => {
    setValueState((prev) => ({
      ...prev,
      [category]: [...prev[category], { id: nextRowId(), key: "", value: "" }],
    }));
    setHasChanges(true);
  }, []);

  const updateValueRow = useCallback(
    (category: MappingValueCategoryName, id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => {
      setValueState((prev) => ({
        ...prev,
        [category]: prev[category].map((row) => (row.id === id ? { ...row, ...updates } : row)),
      }));
      setHasChanges(true);
    },
    [],
  );

  const removeValueRow = useCallback((category: MappingValueCategoryName, id: string) => {
    setValueState((prev) => ({
      ...prev,
      [category]: prev[category].filter((row) => row.id !== id),
    }));
    setHasChanges(true);
  }, []);

  const seedValueDefaults = useCallback(
    (category: MappingValueCategoryName, entries: Record<string, unknown>) => {
      setValueState((prev) => {
        const existingKeys = new Set(prev[category].map((row) => row.key.trim()).filter(Boolean));
        const additions: ValueMapRow[] = Object.entries(entries)
          .filter(([key]) => !existingKeys.has(key))
          .map(([key, value]) => ({
            id: nextRowId(),
            key,
            value: typeof value === "boolean" ? String(value) : value == null ? "" : String(value),
          }));
        if (additions.length === 0) {
          return prev;
        }
        return { ...prev, [category]: [...prev[category], ...additions] };
      });
      setHasChanges(true);
    },
    [],
  );

  return {
    mappingState,
    valueState,
    hasChanges,
    isHydrated,
    hydrate,
    applySuggestedMapping,
    resetChanges,
    setTargetMode,
    setTargetColumns,
    setTargetValue,
    setTargetParser,
    addValueRow,
    updateValueRow,
    removeValueRow,
    seedValueDefaults,
  };
}
