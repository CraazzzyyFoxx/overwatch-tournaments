"use client";

import { useCallback, useRef, useState } from "react";

import {
  capturePngBlob,
  copyImageBlob,
  waitForImages,
  waitForLayout,
} from "@/lib/image-capture";
import { notify } from "@/lib/notify";

export interface NodeCapture {
  /** Attach to the element to rasterise. */
  ref: React.RefObject<HTMLDivElement | null>;
  /** A capture is in flight. Drives the spinner and the re-entry guard. */
  capturing: boolean;
  /**
   * The node as a PNG, for a destination other than the clipboard. `null` when
   * there is nothing to rasterise or a capture is already running; throws when
   * the rasteriser itself fails, so a caller can tell "nothing happened" from
   * "it went wrong".
   */
  rasterize: () => Promise<Blob | null>;
  capture: () => Promise<void>;
}

/**
 * Rasterise a live DOM node to a PNG, for the clipboard or for a caller.
 *
 * For a surface that already looks like what a host wants to share — a matchup
 * card, the lobby board — this beats the off-screen export frame the tournament
 * balancer needs: no second layout to keep in sync, and the image is provably
 * the thing they were looking at. Mark anything that must not appear in the
 * image with `data-export-hide` and hide it while `capturing` is set; use
 * `invisible` rather than `hidden` so the capture measures the same box.
 *
 * The clipboard is not the only destination: `rasterize` hands the same PNG to
 * a caller that ships it somewhere else (the mix posts it to Discord), so the
 * bytes a host sends are provably the bytes they saw. What stays shared is the
 * one `capturing` flag, so `data-export-hide` controls disappear from every
 * capture, and the one re-entry guard.
 *
 * `capture` reports failure and swallows it: a blocked clipboard or a tainted
 * canvas should cost the screenshot, not the screen. `rasterize` throws
 * instead, leaving its caller to decide what a missing image costs.
 */
export function useNodeCapture(): NodeCapture {
  const ref = useRef<HTMLDivElement | null>(null);
  const [capturing, setCapturing] = useState(false);

  const rasterize = useCallback(async () => {
    const node = ref.current;
    // The guard reads state, so it is re-entrancy protection for a double
    // click, not for a concurrent call from elsewhere.
    if (node == null || capturing) return null;

    setCapturing(true);
    try {
      // One frame for the `data-export-hide` class to land, one for layout.
      await waitForLayout();
      await waitForImages(node);

      return await capturePngBlob(node);
    } finally {
      setCapturing(false);
    }
  }, [capturing]);

  const capture = useCallback(async () => {
    try {
      const blob = await rasterize();
      if (blob == null) return;
      await copyImageBlob(blob);
      notify.success("Copied to the clipboard");
    } catch {
      notify.error("Clipboard image copy unavailable");
    }
  }, [rasterize]);

  return { ref, capturing, rasterize, capture };
}
