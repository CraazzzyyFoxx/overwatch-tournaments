"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { dockStack, floatingGlassClass } from "@/components/ui/dock";
import type { Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

/** The rim takes the tone; `neutral` keeps the glass's own control rim. */
const TONE_BORDER: Record<Tone, string> = {
  neutral: "",
  accent: "border-primary/60",
  success: "border-success/60",
  warning: "border-warning/60",
  info: "border-info/60",
  danger: "border-danger/60"
};

interface OverlayBarProps {
  /** Rim accent: `accent` for "you can act now", `warning` for a connectivity/attention problem. */
  tone?: Tone;
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
 * While mounted it publishes two CSS variables on `<html>` -- the footer and
 * the corner docks are never this bar's subtree, so that is the only channel:
 * - `--overlay-bar-h`, its height: the footer (`Footer`) reserves it under its
 *   last row, so the page's end scrolls clear of the bar. Pages add no padding.
 * - `--dock-lift`, the same height while the dock stack (`ui/dock`) runs under
 *   the bar, so the docks stand on it instead of covering the controls it
 *   carries; `0px` while they sit clear of it -- a capped bar on a wide screen
 *   ends short of the corner, and docks lifted there float over nothing.
 */
export function OverlayBar({
  tone = "neutral",
  ariaLabel,
  className,
  children
}: Readonly<OverlayBarProps>) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (node === null) return;
    const root = document.documentElement;
    const stack = dockStack();
    // ponytail: one bar per page; a second one would overwrite the first's values.
    const publish = () => {
      const bar = node.getBoundingClientRect();
      const docks = stack.getBoundingClientRect();
      const underBar = docks.left < bar.right && docks.right > bar.left;
      root.style.setProperty("--overlay-bar-h", `${node.offsetHeight}px`);
      root.style.setProperty("--dock-lift", `${underBar ? node.offsetHeight : 0}px`);
    };
    publish();
    // The stack widens when a dock opens; a capped bar keeps its size while the
    // window resizes, but not its edges.
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    observer.observe(stack);
    window.addEventListener("resize", publish);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", publish);
      root.style.removeProperty("--overlay-bar-h");
      root.style.removeProperty("--dock-lift");
    };
  }, []);

  return (
    <section
      ref={ref}
      className={cn(
        "fixed bottom-2 left-1/2 z-40 w-[min(1320px,94vw)] -translate-x-1/2 p-3 transition-colors supports-[padding:max(0px)]:pb-[max(0.75rem,env(safe-area-inset-bottom))]",
        floatingGlassClass,
        TONE_BORDER[tone],
        className
      )}
      aria-label={ariaLabel}
    >
      {children}
    </section>
  );
}
