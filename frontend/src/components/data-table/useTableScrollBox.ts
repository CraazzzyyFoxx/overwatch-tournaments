"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** A fitted page's bounds: below 5 the box scrolls instead; 100 is the `per_page` cap most list endpoints set. */
const MIN_FIT_ROWS = 5;
const MAX_FIT_ROWS = 100;
/** A resize settles before the page is refitted: in server mode every new size is a request. */
const REFIT_DELAY_MS = 150;

export interface TableScrollBoxOptions {
  /**
   * The page is fitted to the viewport ("Auto"): the box takes all the height
   * left, not only up to it, and `fittedRows` says how many rows that holds.
   */
  fill: boolean;
  /** Row height to fit by while no body row is rendered (loading, empty). */
  rowEstimate: number;
  /** The fitted row count changed from one measured value to another; called in the same batch as the new count. */
  onRefit: (from: number, to: number) => void;
}

/**
 * The table's own scroll box: the element the sticky header and the
 * virtualiser scroll inside, sized to whatever height is left below the card
 * in the viewport so the page itself never scrolls.
 *
 * Measured rather than laid out with flex: the box sits under a dozen
 * different screens' headers and tabs, none of which would otherwise have to
 * know about it.
 */
export function useTableScrollBox({ fill, rowEstimate, onRefit }: TableScrollBoxOptions) {
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
  /** `undefined` until the first fit; `null` when the box has no layout to fit (a DOM without layout). */
  const [fittedRows, setFittedRows] = useState<number | null | undefined>(undefined);
  const fittedRef = useRef<number | null | undefined>(undefined);
  const onRefitRef = useRef(onRefit);
  useLayoutEffect(() => {
    onRefitRef.current = onRefit;
  });

  useEffect(() => {
    const card = cardRef.current;
    const scrollBox = scrollRef.current;
    if (!scrollElement || !scrollBox || !card) return;
    let frame = 0;
    let timer = 0;
    let settled = false;
    let sawRows = false;
    const commit = (rows: number | null) => {
      timer = 0;
      const from = fittedRef.current;
      if (from === rows) return;
      fittedRef.current = rows;
      if (typeof from === "number" && typeof rows === "number") onRefitRef.current(from, rows);
      setFittedRows(rows);
    };
    const fit = () => {
      frame = 0;
      // Measure with the box stretched to a full viewport: at any height that
      // fits, the page is no taller than the shell's own minimum (a screen), so
      // the slack under the card reads as "content below" and the box would
      // lock at whatever height it happened to have. Stretched, the page
      // overflows and only real content is left below the card. The browser
      // may clamp the box's scroll offset meanwhile, so it is put back once the
      // cap returns — without that, every row the virtualiser measured threw
      // the user to the top.
      const { scrollTop, scrollLeft } = scrollBox;
      scrollBox.style.maxHeight = "none";
      scrollBox.style.height = `${window.innerHeight}px`;
      const cardRect = card.getBoundingClientRect();
      const chrome = cardRect.height - scrollBox.getBoundingClientRect().height;
      const cardTop = cardRect.top + window.scrollY;
      const below = Math.max(0, document.documentElement.scrollHeight - (cardRect.bottom + window.scrollY));
      const height = `${Math.max(240, window.innerHeight - cardTop - chrome - below)}px`;
      scrollBox.style.maxHeight = height;
      // Filled, the card ends at the viewport's bottom on every page, the last
      // one included, and the remainder under the last row stays inside it.
      scrollBox.style.height = fill ? height : "";
      scrollBox.scrollTop = scrollTop;
      scrollBox.scrollLeft = scrollLeft;
      if (!fill) return;

      // The shortest body row is the one-line height; taller rows wrap, and a
      // page of them scrolls inside the box like any overflow.
      const rowHeights = Array.from(
        scrollBox.querySelectorAll<HTMLElement>("tbody > tr[data-row-id]"),
        (row) => row.getBoundingClientRect().height
      ).filter((rowHeight) => rowHeight > 0);
      // An empty or loading body has nothing to fit by: only the first fit (the
      // first request needs a size) goes by the estimate; later ones wait for rows.
      if (rowHeights.length === 0 && settled) {
        sawRows = false;
        window.clearTimeout(timer);
        timer = 0;
        return;
      }
      const rowHeight = rowHeights.length > 0 ? Math.min(...rowHeights) : rowEstimate;
      // `clientHeight` leaves out a horizontal scrollbar.
      const space = scrollBox.clientHeight - (scrollBox.querySelector("thead")?.getBoundingClientRect().height ?? 0);
      const rows = space > 0
        ? Math.min(MAX_FIT_ROWS, Math.max(MIN_FIT_ROWS, Math.floor((space + 0.5) / rowHeight)))
        : null;
      // Fitted at once on mount and when real rows replace the estimate (the
      // first page arriving); every later change is a resize, and waits for it.
      const immediate = !settled || !sawRows;
      settled = true;
      sawRows = rowHeights.length > 0;
      window.clearTimeout(timer);
      timer = 0;
      if (rows === fittedRef.current) return;
      if (immediate) commit(rows);
      else timer = window.setTimeout(() => commit(rows), REFIT_DELAY_MS);
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
      window.clearTimeout(timer);
    };
  }, [scrollElement, fill, rowEstimate]);

  return { scrollElement, tableRef, cardRef, fittedRows };
}
