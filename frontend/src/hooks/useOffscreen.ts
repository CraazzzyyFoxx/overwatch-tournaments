import { type RefObject, useEffect, useState } from "react";

/**
 * Whether the element is mostly out of view, for `useAutoplay`'s `held`: a
 * rotation nobody sees must not move on. `false` until observed, and without an
 * `IntersectionObserver` (happy-dom), so it never holds by mistake.
 */
export function useOffscreen(ref: RefObject<Element | null>): boolean {
  const [offscreen, setOffscreen] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setOffscreen(!entry.isIntersecting), { threshold: 0.4 });
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return offscreen;
}
