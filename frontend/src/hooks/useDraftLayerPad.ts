"use client";

import { useEffect, type RefObject } from "react";

/** Tailwind's `xl`: from here each draft-room panel is its own scroller. */
export const DRAFT_WIDE_QUERY = "(min-width: 80rem)";

/** About one list row: less room than this above the card reveals nothing. */
const MIN_ROOM_PX = 48;

/**
 * Pads a room panel's scroller by exactly what the floating pick card hides of
 * it, so the last rows can scroll out from under the card. Only while the card's
 * top edge leaves a row of room inside the scroller: a card as tall as the list
 * covers its rows at every scroll position, and padding for it just added a
 * scrollbar that revealed nothing. Below `xl` the page scrolls instead, and the
 * list's `--draft-layer-h` padding class does the job.
 */
export function useDraftLayerPad(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    const layer = document.querySelector<HTMLElement>("[data-draft-layer]");
    if (!el || !layer) return;
    const wide = window.matchMedia(DRAFT_WIDE_QUERY);
    const sync = () => {
      let pad = "";
      if (wide.matches) {
        const box = el.getBoundingClientRect();
        const card = layer.getBoundingClientRect();
        const hidden = box.bottom - card.top;
        const covers = card.left < box.right && card.right > box.left && hidden > 0;
        pad = covers && card.top - box.top >= MIN_ROOM_PX ? `${Math.ceil(hidden)}px` : "0px";
      }
      el.style.paddingBottom = pad;
      el.style.scrollPaddingBottom = pad;
    };
    sync();
    // Border box: at `xl` it is fixed by the panel, so the padding set here never re-triggers it.
    const observer = new ResizeObserver(sync);
    observer.observe(el, { box: "border-box" });
    observer.observe(layer);
    window.addEventListener("resize", sync);
    window.addEventListener("scroll", sync, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", sync);
      window.removeEventListener("scroll", sync);
      el.style.paddingBottom = "";
      el.style.scrollPaddingBottom = "";
    };
  }, [ref]);
}
