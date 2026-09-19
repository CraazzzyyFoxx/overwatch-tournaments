"use client";

import { useEffect } from "react";

import {
  getInternalNavigationTarget,
  isChangedInternalNavigation,
  shouldIgnoreNavigationClick
} from "@/lib/navigation-guard.mjs";

export interface UnsavedGuardOptions {
  /** Guard is armed only while there is something to lose. */
  dirty: boolean;
  /**
   * Also intercept in-app link clicks, not just a tab close. Off for a form
   * that should not reach outside itself.
   */
  guardNavigation?: boolean;
  /** Called with the internal target instead of navigating to it. */
  onNavigationBlocked: (href: string) => void;
}

/**
 * The two halves of "do not lose my edits": the browser's own unload prompt,
 * and an interception of in-app `next/link` clicks (which never unload the
 * document, so `beforeunload` cannot see them).
 *
 * Extracted from `EntityFormDialog` so the sticky `SaveBar` on every T5
 * settings section gets exactly the same behaviour rather than a second,
 * subtly different copy.
 */
export function useUnsavedGuard({
  dirty,
  guardNavigation = true,
  onNavigationBlocked
}: UnsavedGuardOptions): void {
  useEffect(() => {
    if (!dirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (!dirty || !guardNavigation) return;

    const handleDocumentClick = (event: MouseEvent) => {
      if (shouldIgnoreNavigationClick(event)) return;

      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      const anchor = target.closest("a[href]");
      if (!anchor) return;

      const href = anchor.getAttribute("href");
      if (
        !href ||
        (anchor as HTMLAnchorElement).target === "_blank" ||
        anchor.hasAttribute("download")
      ) {
        return;
      }

      const nextTarget = getInternalNavigationTarget(href, window.location.origin);
      if (!nextTarget) return;
      if (!isChangedInternalNavigation(window.location.href, href, window.location.origin)) return;

      event.preventDefault();
      event.stopPropagation();
      onNavigationBlocked(nextTarget);
    };

    // Capture phase: the anchor's own handlers must not run first.
    document.addEventListener("click", handleDocumentClick, true);
    return () => document.removeEventListener("click", handleDocumentClick, true);
  }, [dirty, guardNavigation, onNavigationBlocked]);
}
