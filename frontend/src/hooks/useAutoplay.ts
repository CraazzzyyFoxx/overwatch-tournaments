import { type FocusEvent, type PointerEvent, useEffect, useState } from "react";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";

/** Where the wait goes: the element whose hover or inner focus holds the rotation. */
export interface AutoplayHoldProps {
  onPointerEnter: (event: PointerEvent<HTMLElement>) => void;
  onPointerLeave: () => void;
  onFocus: () => void;
  onBlur: (event: FocusEvent<HTMLElement>) => void;
}

export interface Autoplay {
  /** The current item, wrapped: the caller's list can shrink under it. */
  index: number;
  /** A pick; it also starts a fresh interval. */
  select: (index: number) => void;
  /** Moving right now: more than one item, autoplay on, nothing holding it. */
  playing: boolean;
  /** The pause/play state the button shows. */
  autoplay: boolean;
  /** The pause/play button: the visitor's choice, and it sticks. */
  toggle: () => void;
  holdProps: AutoplayHoldProps;
}

/**
 * A rotation through `count` items, one every `intervalMs`, with the pause a
 * moving block owes its reader (WCAG 2.2.2): it waits while the pointer is over
 * the element `holdProps` go on, while focus is inside it, and while the caller
 * says `held` (off screen, say); a pick or a resume starts a fresh interval, and
 * the pause/play choice sticks. Under reduced motion it starts stopped. The
 * tournament spotlight, the home hero's results feed and the organizer banner's
 * tabs all turn through this one.
 */
export function useAutoplay(count: number, intervalMs: number, held = false): Autoplay {
  const reduceMotion = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);
  // `null` = still following the reduced-motion default; a boolean is the
  // visitor's own pause/play choice, and it sticks.
  const [override, setOverride] = useState<boolean | null>(null);
  const autoplay = override ?? !reduceMotion;
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const playing = count > 1 && autoplay && !hovered && !focused && !held;

  // One interval per item: a pick (`index`) or a resume (`playing`) starts it over.
  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => setIndex((value) => (value + 1) % count), intervalMs);
    return () => clearTimeout(timer);
  }, [playing, index, count, intervalMs]);

  return {
    index: count > 0 ? index % count : 0,
    select: setIndex,
    playing,
    autoplay,
    toggle: () => setOverride(!autoplay),
    holdProps: {
      // A touch "enter" has no leave until the next tap elsewhere.
      onPointerEnter: (event) => {
        if (event.pointerType === "mouse") setHovered(true);
      },
      onPointerLeave: () => setHovered(false),
      onFocus: () => setFocused(true),
      onBlur: (event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }
    }
  };
}
