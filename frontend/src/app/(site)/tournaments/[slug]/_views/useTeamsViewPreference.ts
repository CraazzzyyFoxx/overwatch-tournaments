"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import type { TeamsView } from "./tournamentTeams.model";

/** Remembers the reader's pick across tournaments; the URL still outranks it. */
const VIEW_STORAGE_KEY = "owt:teams-view";

/**
 * The remembered view is an external store, not React state: it lives in
 * `localStorage`, which the server cannot read. `useSyncExternalStore` is what
 * makes that legal — the server and the hydrating client both take
 * `serverStoredView` (`null`, i.e. "no preference yet"), so the markup agrees,
 * and the real value arrives on the first post-hydration pass.
 *
 * `readStoredView` returns a string or `null`, so repeated calls compare equal
 * and React never sees a store that refuses to settle.
 */
function readStoredView(): TeamsView | null {
  try {
    const saved = window.localStorage.getItem(VIEW_STORAGE_KEY);
    return saved === "list" || saved === "cards" ? saved : null;
  } catch {
    // Private-mode Safari and a locked-down Node both throw on access; a
    // remembered view is a convenience, never a reason to fail the page.
    return null;
  }
}

const serverStoredView = () => null;

// `localStorage` does not notify anyone, so the writer announces the change.
// Module scope because `useSyncExternalStore` keys on callback identity.
const storedViewListeners = new Set<() => void>();
const subscribeStoredView = (onStoreChange: () => void) => {
  storedViewListeners.add(onStoreChange);
  return () => {
    storedViewListeners.delete(onStoreChange);
  };
};

export function writeStoredView(view: TeamsView) {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // See `readStoredView`.
  }
  for (const listener of storedViewListeners) listener();
}

export function useStoredTeamsView(): TeamsView | null {
  return useSyncExternalStore(subscribeStoredView, readStoredView, serverStoredView);
}

/**
 * `true` below the `sm` breakpoint, where `ViewSegment` hides itself. The view
 * follows: a link carrying `?view=cards` opened on a phone still gets the list,
 * because there is no control there to switch back with.
 */
export function useIsNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 639px)");
    const sync = () => setNarrow(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return narrow;
}
