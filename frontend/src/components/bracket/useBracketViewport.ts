"use client";

import { useCallback, useLayoutEffect, useRef, useState, type PointerEvent } from "react";

import { CARD_HEIGHT, CARD_WIDTH } from "./layout";

export const MIN_SCALE = 0.4;
export const MAX_SCALE = 2;
const ZOOM_STEP = 1.2;

export interface BracketViewport {
  scale: number;
  isGrabbing: boolean;
  /** Attach to the scrolling element. Callback ref: the canvas remounts between inline and fullscreen. */
  attachScroller: (el: HTMLDivElement | null) => void;
  scrollerHandlers: {
    onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
    onPointerMove: (event: PointerEvent<HTMLDivElement>) => void;
    onPointerUp: (event: PointerEvent<HTMLDivElement>) => void;
    onPointerCancel: (event: PointerEvent<HTMLDivElement>) => void;
  };
  zoomIn: () => void;
  zoomOut: () => void;
  /** Scale so the whole tree's width fits the scroller, never above 1:1. */
  fit: () => void;
}

/**
 * Pan, zoom and the opening scroll position of the bracket scroller.
 *
 * Drag-to-pan with the mouse (touch keeps native scrolling), Ctrl/⌘+wheel and
 * the toolbar for zoom, and a one-time scroll to `focus` — the top-left of the
 * round in play — when the scroller first mounts. Zoom keeps the point under
 * the cursor (or the viewport centre) still, which is the difference between
 * zooming and lurching.
 */
export function useBracketViewport(params: {
  layoutWidth: number;
  /** Layout-space point to open on, or `null` to leave the scroller at its origin. */
  focus: { x: number; y: number } | null;
}): BracketViewport {
  const { layoutWidth, focus } = params;
  const [scale, setScale] = useState(1);
  const [isGrabbing, setIsGrabbing] = useState(false);
  // Event handlers read the scale through a ref so they stay referentially
  // stable; the layout effect below keeps it current before any input arrives.
  const scaleRef = useRef(scale);
  const elRef = useRef<HTMLDivElement | null>(null);
  // Anchor to hold still across the next scale change, in scroller pixels plus
  // the layout-space point that sat under it.
  const pendingAnchor = useRef<{ ax: number; ay: number; lx: number; ly: number } | null>(null);
  const pan = useRef({ active: false, startX: 0, startY: 0, left: 0, top: 0 });

  const zoomAround = useCallback((next: number, clientX?: number, clientY?: number) => {
    const el = elRef.current;
    const clamped = Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
    const current = scaleRef.current;
    if (clamped === current) return;
    if (el) {
      const rect = el.getBoundingClientRect();
      const ax = clientX === undefined ? el.clientWidth / 2 : clientX - rect.left;
      const ay = clientY === undefined ? el.clientHeight / 2 : clientY - rect.top;
      pendingAnchor.current = {
        ax,
        ay,
        lx: (el.scrollLeft + ax) / current,
        ly: (el.scrollTop + ay) / current
      };
    }
    setScale(clamped);
  }, []);

  // The content has its new size only after React commits the scale, and a
  // scrollLeft set before that clamps against the old extent.
  useLayoutEffect(() => {
    scaleRef.current = scale;
    const el = elRef.current;
    const anchor = pendingAnchor.current;
    if (!el || !anchor) return;
    pendingAnchor.current = null;
    el.scrollLeft = anchor.lx * scale - anchor.ax;
    el.scrollTop = anchor.ly * scale - anchor.ay;
  }, [scale]);

  const onWheel = useCallback(
    (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      // React registers wheel listeners passive, so this has to be a native one
      // for the browser's own page zoom to stay out of it.
      event.preventDefault();
      zoomAround(
        scaleRef.current * (event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP),
        event.clientX,
        event.clientY
      );
    },
    [zoomAround]
  );

  const attachScroller = useCallback(
    (el: HTMLDivElement | null) => {
      elRef.current?.removeEventListener("wheel", onWheel);
      elRef.current = el;
      if (!el) return;
      el.addEventListener("wheel", onWheel, { passive: false });
      // Applied per scroller element, once. `dataset` rather than a ref flag
      // because a re-render (hover, a poll landing) must not yank a viewer who
      // has already panned somewhere else.
      if (!focus || el.dataset.bracketFocused) return;
      el.dataset.bracketFocused = "1";
      const s = scaleRef.current;
      el.scrollLeft = Math.max(0, focus.x * s - (el.clientWidth - CARD_WIDTH * s) / 2);
      el.scrollTop = Math.max(0, focus.y * s - (el.clientHeight - CARD_HEIGHT * s) / 2);
    },
    [focus, onWheel]
  );

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== "mouse" || event.button !== 0) return;
    // Controls keep their clicks; a draggable team row belongs to dnd-kit.
    if ((event.target as HTMLElement).closest("button, a, [data-slot-draggable]")) return;
    const el = event.currentTarget;
    pan.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      left: el.scrollLeft,
      top: el.scrollTop
    };
    el.setPointerCapture?.(event.pointerId);
    setIsGrabbing(true);
  }, []);

  const onPointerMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const p = pan.current;
    if (!p.active) return;
    const el = event.currentTarget;
    el.scrollLeft = p.left - (event.clientX - p.startX);
    el.scrollTop = p.top - (event.clientY - p.startY);
  }, []);

  const onPointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (!pan.current.active) return;
    const el = event.currentTarget;
    if (el.hasPointerCapture?.(event.pointerId)) el.releasePointerCapture(event.pointerId);
    pan.current.active = false;
    setIsGrabbing(false);
  }, []);

  const zoomIn = useCallback(() => zoomAround(scaleRef.current * ZOOM_STEP), [zoomAround]);
  const zoomOut = useCallback(() => zoomAround(scaleRef.current / ZOOM_STEP), [zoomAround]);
  const fit = useCallback(() => {
    const el = elRef.current;
    if (!el || layoutWidth === 0) return;
    zoomAround(Math.min(1, el.clientWidth / layoutWidth));
    // Fitting means seeing the whole width, so the anchor maths is moot: start at the left edge.
    pendingAnchor.current = null;
    el.scrollLeft = 0;
  }, [layoutWidth, zoomAround]);

  return {
    scale,
    isGrabbing,
    attachScroller,
    scrollerHandlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp },
    zoomIn,
    zoomOut,
    fit
  };
}
