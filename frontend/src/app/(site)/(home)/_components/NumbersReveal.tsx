"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { clock } from "@/app/(site)/statistics/_components/statistics.model";
import { useFormatter } from "@/lib/datetime/client";

const COUNT_MS = 1100;

/**
 * A home block's one-shot reveal (the numbers bento, the leaders), played when the block first scrolls into view:
 * every `[data-count]` figure counts up and the charts draw in (`data-reveal`, styled in the block's own CSS module).
 * The server markup is the final state and stays so unless the block is still off-screen on mount: already in view,
 * under reduced motion or with no `IntersectionObserver` (happy-dom), nothing moves.
 *
 * A figure counts inside its own text: the target, formatted, is swapped for the running value, so whatever is
 * around it stays (`−412 SR`); `data-clock` counts seconds as `m:ss`. `as="dl"` when the block is a list of facts.
 */
export function NumbersReveal({
  as: Tag = "div",
  className,
  children
}: Readonly<{ as?: "div" | "dl"; className?: string; children: ReactNode }>) {
  const ref = useRef<HTMLElement | null>(null);
  const format = useFormatter();

  useEffect(() => {
    const root = ref.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const { top, bottom } = root.getBoundingClientRect();
    if (top < innerHeight && bottom > 0) return;

    // The text nodes React rendered are rewritten in place, never replaced, so React keeps owning them; the last
    // frame puts back the server's own string.
    const figures = Array.from(root.querySelectorAll<HTMLElement>("[data-count]"), (element) => {
      const final = element.textContent ?? "";
      const target = Number(element.dataset.count);
      const shown = format.number(Math.round(target));
      return {
        text: element.firstChild as Text,
        final,
        target,
        at: (value: number) =>
          element.dataset.clock === undefined ? final.replace(shown, format.number(value)) : clock(value)
      };
    });
    const paint = (progress: number) => {
      for (const { text, final, target, at } of figures) {
        text.data = progress < 1 ? at(Math.round(target * (1 - (1 - progress) ** 3))) : final;
      }
    };

    let frame = 0;
    paint(0);
    root.dataset.reveal = "armed";
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        root.dataset.reveal = "in";
        const start = performance.now();
        const step = (now: number) => {
          const progress = Math.min(1, (now - start) / COUNT_MS);
          paint(progress);
          if (progress < 1) frame = requestAnimationFrame(step);
        };
        frame = requestAnimationFrame(step);
      },
      // Plays once the block's top clears the bottom sixth of the window, not on its first pixel.
      { rootMargin: "0px 0px -15% 0px" }
    );
    observer.observe(root);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      paint(1);
      delete root.dataset.reveal;
    };
  }, [format]);

  return (
    // A callback ref, as one fits either element's ref type.
    <Tag
      ref={(node: HTMLElement | null) => {
        ref.current = node;
      }}
      className={className}
    >
      {children}
    </Tag>
  );
}
