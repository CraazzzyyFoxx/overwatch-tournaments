"use client";

import { useEffect, useEffectEvent, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

interface InfiniteScrollOptions {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
  /**
   * How far below the viewport the sentinel starts loading. The default fetches
   * roughly one screen ahead so the next rows are already in place by the time
   * the user reaches them.
   */
  rootMargin?: string;
  /** Scroll container. Omit when the page itself scrolls. */
  root?: Element | null;
  /**
   * The last page request failed. Auto-loading MUST stop here: the sentinel
   * stays on screen after a failure, so re-observing would retry forever
   * (measured: 16 requests in 5s against a failing endpoint).
   */
  isError?: boolean;
  /** Pause auto-loading (a filter change in flight, a collapsed panel). */
  disabled?: boolean;
}

/**
 * Ref for a sentinel element that loads the next page when it scrolls near view.
 *
 * The observer is rebuilt whenever the paging state changes on purpose: a fresh
 * observer reports the sentinel's *current* intersection, so a short first page
 * that leaves the sentinel already on screen keeps filling the viewport instead
 * of waiting for a scroll event that never comes.
 */
export function useInfiniteScroll({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  rootMargin = "320px",
  root,
  isError = false,
  disabled = false
}: InfiniteScrollOptions) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // Keeps the observer subscription off the callback's identity.
  const loadNext = useEffectEvent(() => fetchNextPage());

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || disabled || isError || !hasNextPage || isFetchingNextPage) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadNext();
      },
      { root: root ?? null, rootMargin }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [disabled, hasNextPage, isError, isFetchingNextPage, root, rootMargin]);

  return sentinelRef;
}

interface InfiniteScrollFooterProps extends InfiniteScrollOptions {
  /** Rows already rendered. Announced so progress is audible, not just visible. */
  loaded: number;
  /** Rows the current filter matches server-side, when known. */
  total?: number;
  /** Plural noun for the rows, e.g. "logs". */
  unit: string;
  loadMoreLabel?: string;
  /**
   * Replaces the built-in "Showing N of M unit" line. The defaults are English
   * literals; a next-intl page passes its own translated node instead.
   */
  progressLabel?: ReactNode;
  /** Replaces the built-in failure sentence. */
  errorLabel?: string;
  className?: string;
}

/**
 * The list footer that drives infinite scrolling.
 *
 * Auto-loading alone is not an interface: the button is always rendered so the
 * next page is reachable by keyboard and pointer even when the observer never
 * fires, and the status line is a stable live region whose text is replaced on
 * each page (a region created per update announces unreliably).
 */
export function InfiniteScrollFooter({
  loaded,
  total,
  unit,
  loadMoreLabel,
  progressLabel,
  errorLabel,
  className,
  ...options
}: Readonly<InfiniteScrollFooterProps>) {
  const sentinelRef = useInfiniteScroll(options);
  const { hasNextPage, isFetchingNextPage, fetchNextPage, isError, disabled } = options;

  const progress =
    progressLabel ??
    (total != null
      ? `Showing ${loaded.toLocaleString()} of ${total.toLocaleString()} ${unit}`
      : `Showing ${loaded.toLocaleString()} ${unit}`);

  return (
    <div className={cn("flex flex-col items-center gap-2 pt-1", className)}>
      <output
        className={cn("text-xs tabular-nums", isError ? "text-danger" : "text-muted-foreground")}
      >
        {isError
          ? (errorLabel ?? `Unable to load more ${unit}. Check your connection and try again.`)
          : isFetchingNextPage
            ? `Loading more ${unit}…`
            : progress}
      </output>
      {hasNextPage ? (
        <>
          <div ref={sentinelRef} aria-hidden className="h-px w-full" />
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            disabled={isFetchingNextPage || disabled}
            onClick={() => fetchNextPage()}
          >
            {isFetchingNextPage ? <Spinner /> : null}
            {isError ? `Try loading ${unit} again` : (loadMoreLabel ?? `Load more ${unit}`)}
          </Button>
        </>
      ) : null}
    </div>
  );
}
