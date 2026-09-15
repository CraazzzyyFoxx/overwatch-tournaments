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

/** Pointer travel before a press on a row body becomes a sweep rather than a click. */
const ROW_DRAG_THRESHOLD = 6;

/** Controls inside a row own their own clicks; the row must not treat them as row gestures. */
export function isInteractiveRowTarget(target: HTMLElement) {
  return Boolean(target.closest("button, a, input, select, textarea, [role='button'], [role='link'], [data-radix-collection-item]"));
}

/**
 * Mouse, touch and keyboard selection gestures for the admin table, in the
 * spreadsheet idiom.
 *
 * Pointer: press a checkbox or a row body and sweep across neighbours to give
 * them the same state; Shift+click extends from the last pressed row and
 * Ctrl/Cmd+click toggles one row. A plain click on a row body is left alone so
 * the screen's `onRowClick` (the inspector) still works; `consumeClick` tells
 * that handler when the press it is reacting to was a selection gesture.
 *
 * Hit-testing goes through `elementFromPoint` rather than per-row
 * `pointerenter`: touch pointers are implicitly captured by the element they
 * started on, so no other row ever sees them, and rows sliding under a
 * stationary pointer during autoscroll fire no boundary events either. Rows
 * opt in with `data-row-id={row.id}`.
 *
 * Keyboard (`bodyKeyDown` on the `<tbody>`): arrows move focus between rows,
 * Shift+arrow grows the range from the anchor, Space toggles, Ctrl/Cmd+A
 * selects the page, Escape clears.
 */
export function useRowSelectionGestures<TData>(table: Table<TData>, selectable: boolean) {
  const dragRef = useRef<Drag | null>(null);
  const anchorRef = useRef<string | null>(null);
  /** The click that follows this press belongs to a selection gesture, not to `onRowClick`. */
  const suppressClickRef = useRef(false);

  const rowAt = (x: number, y: number): Row<TData> | undefined => {
    const id = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-row-id]")?.dataset.rowId;
    return id === undefined ? undefined : table.getRowModel().rowsById[id];
  };

  /**
   * Applies `value` to every row between two ids in display order, inclusive.
   * Goes through one `setRowSelection` updater rather than per-row
   * `toggleSelected`: that one short-circuits on the row's selected state as
   * of the call, so two toggles of the same row in one tick lose the second.
   */
  const paintRange = (fromId: string, toId: string, value: boolean) => {
    const rows = table.getRowModel().rows;
    const a = rows.findIndex((r) => r.id === fromId);
    const b = rows.findIndex((r) => r.id === toId);
    if (a < 0 || b < 0) return;
    table.setRowSelection((old) => {
      const next = { ...old };
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) {
        const row = rows[i];
        if (!row.getCanSelect()) continue;
        if (value) next[row.id] = true;
        else delete next[row.id];
      }
      return next;
    });
  };

  const end = () => {
    const drag = dragRef.current;
    if (!drag) return;
    cancelAnimationFrame(drag.frame);
    drag.listeners.abort();
    document.body.style.userSelect = "";
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

  const startDrag = (value: boolean, x: number, y: number, scroller: Element) => {
    end();
    const listeners = new AbortController();
    const { signal } = listeners;
    window.addEventListener("pointermove", onPointerMove, { signal });
    window.addEventListener("pointerup", end, { signal });
    window.addEventListener("pointercancel", end, { signal });
    dragRef.current = { value, x, y, scroller, frame: requestAnimationFrame(tick), listeners };
  };

  return {
    /** Reports (and clears) whether the click now firing was the tail of a selection gesture. */
    consumeClick: () => {
      const suppressed = suppressClickRef.current;
      suppressClickRef.current = false;
      return suppressed;
    },
    checkboxPointerDown: (row: Row<TData>) => (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      // No text selection while sweeping, no focus jump to the checkbox.
      event.preventDefault();
      const value = !row.getIsSelected();
      if (event.shiftKey && anchorRef.current !== null) paintRange(anchorRef.current, row.id, value);
      else row.toggleSelected(value);
      anchorRef.current = row.id;
      startDrag(value, event.clientX, event.clientY, scrollParent(event.currentTarget));
    },
    /**
     * Spreadsheet-style gestures on the row body. Ctrl/Cmd+click toggles,
     * Shift+click extends from the anchor, and a press that travels onto
     * another row becomes a sweep; only then is the plain click taken away
     * from `onRowClick`, so text in a cell can still be selected and a still
     * click still opens the row.
     */
    rowPointerDown: (row: Row<TData>) => (event: React.PointerEvent<HTMLElement>) => {
      suppressClickRef.current = false;
      if (!selectable || event.button !== 0 || dragRef.current) return;
      if (isInteractiveRowTarget(event.target as HTMLElement)) return;
      if (event.ctrlKey || event.metaKey) {
        if (!row.getCanSelect()) return;
        row.toggleSelected();
        anchorRef.current = row.id;
        suppressClickRef.current = true;
        return;
      }
      if (event.shiftKey) {
        // Native Shift+click would extend the text selection instead.
        event.preventDefault();
        paintRange(anchorRef.current ?? row.id, row.id, true);
        anchorRef.current ??= row.id;
        suppressClickRef.current = true;
        return;
      }
      const origin = { x: event.clientX, y: event.clientY };
      const scroller = scrollParent(event.currentTarget);
      const armed = new AbortController();
      const { signal } = armed;
      window.addEventListener("pointerup", () => armed.abort(), { signal });
      window.addEventListener("pointercancel", () => armed.abort(), { signal });
      window.addEventListener(
        "pointermove",
        (move) => {
          if (Math.hypot(move.clientX - origin.x, move.clientY - origin.y) < ROW_DRAG_THRESHOLD) return;
          const under = rowAt(move.clientX, move.clientY);
          if (!under || under.id === row.id) return;
          armed.abort();
          const value = !row.getIsSelected();
          paintRange(row.id, under.id, value);
          anchorRef.current = row.id;
          suppressClickRef.current = true;
          document.getSelection()?.removeAllRanges();
          document.body.style.userSelect = "none";
          startDrag(value, move.clientX, move.clientY, scroller);
        },
        { signal }
      );
    },
    /**
     * Radix toggles on click, but the pointer press above already did. A
     * keyboard "click" (Space/Enter) has `detail === 0` and must still toggle.
     */
    checkboxClick: (event: React.MouseEvent<HTMLElement>) => {
      if (event.detail !== 0) event.preventDefault();
    },
    /**
     * Returns true when the key was consumed, so the caller can leave Enter and
     * everything else to its own row-action handling.
     */
    bodyKeyDown: (event: React.KeyboardEvent<HTMLElement>): boolean => {
      const current = (event.target as HTMLElement).closest<HTMLElement>("[data-row-id]");
      if (!current || current !== event.target) return false;
      const rowElements = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-row-id]")];
      const index = rowElements.indexOf(current);
      const rowId = current.dataset.rowId!;
      const row = table.getRowModel().rowsById[rowId];

      let target: number | null = null;
      switch (event.key) {
        case "ArrowDown":
          target = Math.min(index + 1, rowElements.length - 1);
          break;
        case "ArrowUp":
          target = Math.max(index - 1, 0);
          break;
        case "Home":
          target = 0;
          break;
        case "End":
          target = rowElements.length - 1;
          break;
        case " ":
          if (!selectable || !row) return false;
          event.preventDefault();
          row.toggleSelected();
          anchorRef.current = rowId;
          return true;
        case "Escape":
          if (!selectable) return false;
          table.resetRowSelection();
          return true;
        case "a":
        case "A":
          if (!selectable || !(event.ctrlKey || event.metaKey)) return false;
          event.preventDefault();
          table.toggleAllPageRowsSelected(true);
          return true;
        default:
          return false;
      }

      event.preventDefault();
      const next = rowElements[target];
      if (event.shiftKey && selectable && row) {
        // The contiguous block from the anchor is what the arrow is resizing:
        // drop the old block, paint the new one. Selections made elsewhere stay.
        const anchor = anchorRef.current ?? rowId;
        anchorRef.current = anchor;
        paintRange(anchor, rowId, false);
        paintRange(anchor, next.dataset.rowId!, true);
      }
      next.focus();
      return true;
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
