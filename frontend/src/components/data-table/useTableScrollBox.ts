"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The table's own scroll box: the element the sticky header and the
 * virtualiser scroll inside, sized to whatever height is left below the card
 * in the viewport so the page itself never scrolls.
 *
 * Measured rather than laid out with flex: the box sits under a dozen
 * different screens' headers and tabs, none of which would otherwise have to
 * know about it.
 */
export function useTableScrollBox() {
  // The element is held twice on purpose: the state re-renders the table once
  // the box exists (the virtualiser needs it), while the box is only ever
  // measured and capped through the ref — state values are not for mutating.
  const scrollRef = useRef<HTMLElement | null>(null);
  const [scrollElement, setScrollElement] = useState<HTMLElement | null>(null);
  // The shadcn `Table` wraps the `<table>` in the element that actually scrolls.
  const tableRef = useCallback((table: HTMLTableElement | null) => {
    scrollRef.current = table?.parentElement ?? null;
    setScrollElement(scrollRef.current);
  }, []);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const card = cardRef.current;
    const scrollBox = scrollRef.current;
    if (!scrollElement || !scrollBox || !card) return;
    let frame = 0;
    const fit = () => {
      frame = 0;
      // Measure with the cap lifted: with the box capped, a page shorter than
      // the viewport reports the slack under the card as "content below", and
      // the cap would lock at whatever height the box happened to have.
      // Uncapped, the box no longer overflows and the browser clamps its
      // scroll offset to 0, so it is put back once the cap returns — without
      // that, every row the virtualiser measured threw the user to the top.
      const { scrollTop, scrollLeft } = scrollBox;
      scrollBox.style.maxHeight = "";
      const cardRect = card.getBoundingClientRect();
      const chrome = cardRect.height - scrollBox.getBoundingClientRect().height;
      const cardTop = cardRect.top + window.scrollY;
      const below = Math.max(0, document.documentElement.scrollHeight - (cardRect.bottom + window.scrollY));
      scrollBox.style.maxHeight = `${Math.max(240, window.innerHeight - cardTop - chrome - below)}px`;
      scrollBox.scrollTop = scrollTop;
      scrollBox.scrollLeft = scrollLeft;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(fit); };
    fit();
    window.addEventListener("resize", schedule);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    // The table grows and shrinks with its rows inside a capped box, which the
    // box itself never reports; the card reports toolbar/footer changes.
    // ponytail: headers collapsing above the card on a page that does not
    // overflow are not observed; add an observer on the page container if it shows.
    observer?.observe(scrollBox.firstElementChild ?? scrollBox);
    observer?.observe(card);
    return () => {
      window.removeEventListener("resize", schedule);
      observer?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [scrollElement]);

  return { scrollElement, tableRef, cardRef };
}
