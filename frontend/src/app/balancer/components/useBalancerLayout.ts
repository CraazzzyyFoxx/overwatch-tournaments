"use client";

import { useEffect, useState, type RefObject } from "react";

import { type BalancerOperationStepDefinition } from "./BalancerOperationDialog";

export const EXPORT_TO_TOURNAMENT_STEPS: BalancerOperationStepDefinition[] = [
  {
    id: "validate",
    label: "Validate selected balance",
    description: "Check that the selected result can be exported."
  },
  {
    id: "save",
    label: "Save selected balance",
    description: "Persist the current teams before exporting them."
  },
  {
    id: "export",
    label: "Create tournament teams",
    description: "Replace previously exported teams and create tournament rosters."
  },
  {
    id: "refresh",
    label: "Refresh tournament data",
    description: "Update cached balance, team, standings, and public tournament views."
  }
];

export const IMPORT_JSON_STEPS: BalancerOperationStepDefinition[] = [
  {
    id: "read",
    label: "Read JSON file",
    description: "Parse the file and check that it holds a balance payload."
  },
  {
    id: "load",
    label: "Load balance preview",
    description: "Add it to the variant list so it can be reviewed, saved or exported."
  }
];

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
  const [isWide, setIsWide] = useState(true);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1280px)");
    const sync = () => setIsWide(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, []);

  return isWide;
}

/**
 * `react-resizable-panels` only speaks percentages, so every fixed width on this
 * page — the 56px collapsed rail, the width a sidebar row stops fitting at —
 * has to be converted against the live group width. A flat `collapsedSize={5}`
 * grew with the viewport: 78px at 1568px, wider still on a 4K monitor.
 */
export const RAIL_WIDTH_PX = 56;
/** Below this a sidebar row clips its own controls (measured at 200px: 4px over). */
export const SIDEBAR_MIN_PX = 260;

export function useGroupWidth(groupRef: RefObject<HTMLDivElement | null>): number {
  // Desktop-first seed, matching `useIsWideBalancerLayout`'s optimism, so the
  // first paint is close and the corrected value is a nudge rather than a jump.
  const [width, setWidth] = useState(1280);

  useEffect(() => {
    const element = groupRef.current;
    if (!element) return;

    const sync = () => {
      const next = element.getBoundingClientRect().width;
      if (next > 0) setWidth(next);
    };

    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(element);
    return () => observer.disconnect();
  }, [groupRef]);

  return width;
}
