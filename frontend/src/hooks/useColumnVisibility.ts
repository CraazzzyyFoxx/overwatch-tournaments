import { useCallback, useMemo, useState } from "react";

interface VisibilityColumn {
  id: string;
  defaultVisible: boolean;
}

function loadVisibility(
  storageKey: string,
): Record<string, boolean> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return null;
    return JSON.parse(raw) as Record<string, boolean>;
  } catch {
    return null;
  }
}

function saveVisibility(
  storageKey: string,
  visibility: Record<string, boolean>,
) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(visibility));
  } catch {
    // localStorage full or unavailable — ignore
  }
}

export function useColumnVisibility<T extends VisibilityColumn>(
  storageKey: string,
  columns: T[],
) {
  const defaults = useMemo(() => {
    const d: Record<string, boolean> = {};
    for (const col of columns) {
      d[col.id] = col.defaultVisible;
    }
    return d;
  }, [columns]);

  const [visibility, setVisibility] = useState<Record<string, boolean>>(
    () => {
      const stored = loadVisibility(storageKey);
      if (!stored) return defaults;
      // Merge: keep stored values for known columns, use defaults for new ones
      const merged: Record<string, boolean> = { ...defaults };
      for (const key of Object.keys(merged)) {
        if (key in stored) {
          merged[key] = stored[key];
        }
      }
      return merged;
    },
  );

  const visibleColumns = useMemo(
    () => columns.filter((col) => visibility[col.id] !== false),
    [columns, visibility],
  );

  const toggleColumn = useCallback(
    (id: string) => {
      setVisibility((prev) => {
        const next = { ...prev, [id]: !prev[id] };
        saveVisibility(storageKey, next);
        return next;
      });
    },
    [storageKey],
  );

  const resetToDefaults = useCallback(() => {
    setVisibility(defaults);
    saveVisibility(storageKey, defaults);
  }, [storageKey, defaults]);

  return { visibleColumns, visibility, toggleColumn, resetToDefaults };
}
