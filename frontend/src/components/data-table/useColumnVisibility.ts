import { useCallback, useMemo, useState } from "react";

interface VisibilityColumn {
  id: string;
  defaultVisible: boolean;
}

function loadVisibility(storageKey: string | null): Record<string, boolean> | null {
  if (storageKey === null || typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return null;
    return JSON.parse(raw) as Record<string, boolean>;
  } catch {
    return null;
  }
}

function saveVisibility(storageKey: string | null, visibility: Record<string, boolean>) {
  if (storageKey === null || typeof window === "undefined") return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(visibility));
  } catch {
    // localStorage full or unavailable — ignore
  }
}

/**
 * Column visibility, persisted per table. A `null` storage key keeps the
 * choice in memory only — for a table that does not offer the picker.
 */
export function useColumnVisibility<T extends VisibilityColumn>(
  storageKey: string | null,
  columns: T[],
) {
  const defaults = useMemo(() => {
    const d: Record<string, boolean> = {};
    for (const col of columns) {
      d[col.id] = col.defaultVisible;
    }
    return d;
  }, [columns]);

  // Loaded once: what the user last chose, for whatever columns existed then.
  const [stored] = useState(() => loadVisibility(storageKey) ?? {});
  // Only what the user toggled in this session. Keeping the state this thin is
  // what lets a column that appears LATER — one per organizer-defined form
  // field, say — still honour its own default: a merged snapshot taken at
  // mount could not know about it, and TanStack shows any column missing from
  // the visibility map, so `defaultHidden` was silently ignored.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  const visibility = useMemo(() => {
    const next: Record<string, boolean> = {};
    for (const [id, fallback] of Object.entries(defaults)) {
      next[id] = overrides[id] ?? stored[id] ?? fallback;
    }
    return next;
  }, [defaults, overrides, stored]);

  const toggleColumn = useCallback(
    (id: string) => {
      setOverrides((prev) => {
        const current = prev[id] ?? stored[id] ?? defaults[id] ?? true;
        const next = { ...prev, [id]: !current };
        saveVisibility(storageKey, { ...stored, ...next });
        return next;
      });
    },
    [storageKey, stored, defaults]
  );

  /** Replaces the whole map at once — saved views restore a full snapshot. */
  const setVisibility = useCallback(
    (next: Record<string, boolean>) => {
      setOverrides(next);
      saveVisibility(storageKey, next);
    },
    [storageKey]
  );

  const resetToDefaults = useCallback(() => {
    setOverrides(defaults);
    saveVisibility(storageKey, defaults);
  }, [storageKey, defaults]);

  return { visibility, toggleColumn, setVisibility, resetToDefaults };
}
