"use client";

import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type OverlayBarTone = "neutral" | "warn" | "active";

const TONE_BORDER: Record<OverlayBarTone, string> = {
  neutral: "border-[color:var(--aqt-border-2)]",
  warn: "border-[color:var(--aqt-warm)]/60",
  active: "border-[color:var(--aqt-teal)]/60",
};

interface OverlayBarProps {
  /** Border accent -- "warn" for a connectivity/attention problem, "active" for "you can act now". */
  tone?: OverlayBarTone;
  ariaLabel?: string;
  className?: string;
  children: ReactNode;
}

/**
 * Fixed bottom-center overlay shell for a page's primary "act now" control
 * surface -- centered, width-capped, backdrop-blurred, safe-area-aware.
 * Shared so any room anchoring a live turn/command bar (e.g. the pick-ban
 * pregame room) gets the same positioning and chrome instead of duplicating it.
 *
 * Pair with bottom padding on the page's scroll container so the fixed bar
 * never overlaps trailing content.
 */
export function OverlayBar({ tone = "neutral", ariaLabel, className, children }: Readonly<OverlayBarProps>) {
  return (
    <section
      className={cn(
        "fixed bottom-2 left-1/2 z-40 w-[min(1320px,94vw)] -translate-x-1/2 rounded-xl border bg-[color:var(--aqt-card)]/95 p-3 shadow-xl backdrop-blur transition-colors supports-[padding:max(0px)]:pb-[max(0.75rem,env(safe-area-inset-bottom))]",
        TONE_BORDER[tone],
        className,
      )}
      aria-label={ariaLabel}
    >
      {children}
    </section>
  );
}
