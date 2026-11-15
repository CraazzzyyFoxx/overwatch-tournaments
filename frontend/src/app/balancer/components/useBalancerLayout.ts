"use client";

import { useCallback, useEffect, useRef } from "react";
import type { GroupImperativeHandle, Layout } from "react-resizable-panels";

import { useMediaQuery } from "@/hooks/useMediaQuery";

import type { BalancerOperationStepId } from "./operation-steps";

export const EXPORT_TO_TOURNAMENT_STEPS: readonly BalancerOperationStepId[] = [
  "validate",
  "save",
  "export",
  "refresh"
];

export const IMPORT_JSON_STEPS: readonly BalancerOperationStepId[] = ["read", "load"];

export function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

/**
 * The Balancing Pool sidebar only sits beside the balance editor at desktop
 * widths (Tailwind's `xl` breakpoint, 1280px); narrower viewports stack the
 * two panels in a single column instead. Defaults to `true` (desktop-first)
 * so the common case matches between server render and hydration.
 */
export function useIsWideBalancerLayout(): boolean {
  return useMediaQuery("(min-width: 1280px)", true);
}

/**
 * Panel sizes: `react-resizable-panels` reads a bare number as pixels, so the
 * fixed widths on this page — the 56px collapsed rail, the width a sidebar row
 * stops fitting at — are passed as numbers; proportional sizes are `"NN%"` strings.
 */
export const RAIL_WIDTH_PX = 56;
/** Below this a sidebar row clips its own controls (measured at 200px: 4px over). */
export const SIDEBAR_MIN_PX = 260;

export const POOL_PANEL_ID = "balancer-pool-sidebar-panel";
export const CONTENT_PANEL_ID = "balancer-pool-content-panel";
export const PLAYERS_PANEL_ID = "balancer-players-sidebar-panel";

/**
 * Remembers the panel layout across visits. The saved layout is applied after mount,
 * not handed to the group as `defaultLayout`: that is read from `localStorage` during
 * render, so a returning visitor's first client render would disagree with the server
 * HTML and React keeps the server's stale `flex-basis` styles on the panels.
 * Panel sets differ per tournament state, so each id set has its own entry. `active` is whether
 * the group is mounted at all (it only is at wide widths).
 */
export function usePersistedPanelLayout(groupId: string, panelIds: readonly string[], active: boolean) {
  const groupRef = useRef<GroupImperativeHandle>(null);
  const storageKey = `${groupId}:${panelIds.join(":")}`;
  // Until the saved layout is applied, the group's own initial layout reports are not worth saving.
  const restoredKey = useRef<string | null>(null);

  useEffect(() => {
    if (!active) {
      restoredKey.current = null;
      return;
    }
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved) groupRef.current?.setLayout(JSON.parse(saved));
    } catch {
      // Unreadable or stale entry (or no storage): keep the default layout.
    }
    restoredKey.current = storageKey;
  }, [active, storageKey]);

  const onLayoutChanged = useCallback(
    (layout: Layout) => {
      if (restoredKey.current !== storageKey) return;
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(layout));
      } catch {
        // Storage full or unavailable: the layout just is not remembered.
      }
    },
    [storageKey]
  );

  return { groupRef, onLayoutChanged };
}
