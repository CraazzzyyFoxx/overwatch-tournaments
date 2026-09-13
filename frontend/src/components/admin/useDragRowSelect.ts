"use client";

import { useEffect, useRef } from "react";
import type { Row, Table } from "@tanstack/react-table";

/** Pointer this close to the scroller's edge drags the content along. */
const AUTOSCROLL_EDGE = 48;
const AUTOSCROLL_MAX_STEP = 32;

interface Drag {
  /** Selection state being painted onto every row swept over. */
  value: boolean;
  x: number;
  y: number;
  scroller: Element;
  frame: number;
  listeners: AbortController;
}

/**
 * Paint-select for the admin table: press a row's checkbox and sweep across
 * neighbours to give them the same state; shift-press extends the selection
 * from the last pressed row.
 *
 * Hit-testing goes through `elementFromPoint` rather than per-row
 * `pointerenter`: touch pointers are implicitly captured by the element they
 * started on, so no other row ever sees them, and rows sliding under a
 * stationary pointer during autoscroll fire no boundary events either. Rows
 * opt in with `data-row-id={row.id}`.
 */
export function useDragRowSelect<TData>(table: Table<TData>) {
  const dragRef = useRef<Drag | null>(null);
  const anchorRef = useRef<string | null>(null);

  const rowAt = (x: number, y: number): Row<TData> | undefined => {
    const id = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-row-id]")?.dataset.rowId;
    return id === undefined ? undefined : table.getRowModel().rowsById[id];
  };

  const end = () => {
    const drag = dragRef.current;
    if (!drag) return;
    cancelAnimationFrame(drag.frame);
    drag.listeners.abort();
    dragRef.current = null;
  };

  const tick = () => {
    const drag = dragRef.current;
    if (!drag) return;
    const { top, bottom } =
      drag.scroller === document.scrollingElement
        ? { top: 0, bottom: window.innerHeight }
        : drag.scroller.getBoundingClientRect();
    const overshoot =
      drag.y < top + AUTOSCROLL_EDGE
        ? drag.y - (top + AUTOSCROLL_EDGE)
        : drag.y > bottom - AUTOSCROLL_EDGE
          ? drag.y - (bottom - AUTOSCROLL_EDGE)
          : 0;
    if (overshoot !== 0) {
      drag.scroller.scrollBy(0, Math.sign(overshoot) * Math.min(AUTOSCROLL_MAX_STEP, Math.abs(overshoot) / 2));
      rowAt(drag.x, drag.y)?.toggleSelected(drag.value);
    }
    drag.frame = requestAnimationFrame(tick);
  };

  const onPointerMove = (event: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    drag.x = event.clientX;
    drag.y = event.clientY;
    rowAt(drag.x, drag.y)?.toggleSelected(drag.value);
  };

  useEffect(() => end, []);

  return {
    checkboxPointerDown: (row: Row<TData>) => (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      // No text selection while sweeping, no focus jump to the checkbox.
      event.preventDefault();
      const value = !row.getIsSelected();
      const rows = table.getRowModel().rows;
      const anchorIndex = event.shiftKey ? rows.findIndex((r) => r.id === anchorRef.current) : -1;
      if (anchorIndex >= 0) {
        const targetIndex = rows.findIndex((r) => r.id === row.id);
        const [from, to] = anchorIndex < targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
        for (let i = from; i <= to; i++) rows[i].toggleSelected(value);
      } else {
        row.toggleSelected(value);
      }
      anchorRef.current = row.id;

      end();
      const listeners = new AbortController();
      const { signal } = listeners;
      window.addEventListener("pointermove", onPointerMove, { signal });
      window.addEventListener("pointerup", end, { signal });
      window.addEventListener("pointercancel", end, { signal });
      dragRef.current = {
        value,
        x: event.clientX,
        y: event.clientY,
        scroller: scrollParent(event.currentTarget),
        frame: requestAnimationFrame(tick),
        listeners,
      };
    },
    /**
     * Radix toggles on click, but the pointer press above already did. A
     * keyboard "click" (Space/Enter) has `detail === 0` and must still toggle.
     */
    checkboxClick: (event: React.MouseEvent<HTMLElement>) => {
      if (event.detail !== 0) event.preventDefault();
    },
  };
}

function scrollParent(el: HTMLElement): Element {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight) return node;
  }
  return document.scrollingElement ?? document.documentElement;
}
