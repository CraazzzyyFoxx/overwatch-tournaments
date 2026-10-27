"use client";

import { useEffect, useEffectEvent, useRef, type ReactNode } from "react";
import { useTranslations } from "next-intl";

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
function useInfiniteScroll({
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
  /** Translated plural noun for the rows ("logs", "турниров"); "rows" by default. */
  unit?: string;
  /** `sm` under a dense table; `lg` the public feed's full-width button. */
  size?: "sm" | "lg";
  /** Overrides the built-in "Load more …" label. */
  loadMoreLabel?: string;
  /** Overrides the built-in "Showing N of M …" line (a caller with its own plural rules). */
  progressLabel?: ReactNode;
  /** Overrides the built-in failure sentence. */
  errorLabel?: string;
  className?: string;
}

/**
 * The list footer that drives infinite scrolling.
 *
 * Auto-loading alone is not an interface: the button is always rendered so the
 * next page is reachable by keyboard and pointer even when the observer never
 * fires, and the status line is a stable live region whose text is replaced on
 * each page (a region created per update announces unreliably). Progress is
 * screen-reader-only: the rows themselves show it; only a failure is visible.
 */
export function InfiniteScrollFooter({
  loaded,
  total,
  unit,
  size = "sm",
  loadMoreLabel,
  progressLabel,
  errorLabel,
  className,
  ...options
}: Readonly<InfiniteScrollFooterProps>) {
  const t = useTranslations("kit.ui.infiniteScroll");
  const sentinelRef = useInfiniteScroll(options);
  const { hasNextPage, isFetchingNextPage, fetchNextPage, isError, disabled } = options;
  const noun = unit ?? t("rows");

  const progress =
    progressLabel ??
    (total != null
      ? t("progressOf", { loaded, total, unit: noun })
      : t("progress", { loaded, unit: noun }));

  return (
    <div className={cn("flex flex-col items-center gap-2 pt-1", className)}>
      <output className={cn("text-caption tabular-nums", isError ? "text-danger" : "sr-only")}>
        {isError
          ? (errorLabel ?? t("error", { unit: noun }))
          : isFetchingNextPage
            ? t("loading", { unit: noun })
            : progress}
      </output>
      {hasNextPage ? (
        <>
          <div ref={sentinelRef} aria-hidden className="h-px w-full" />
          <Button
            type="button"
            variant="outline"
            size={size}
            className={size === "lg" ? "w-full max-w-sm" : undefined}
            disabled={isFetchingNextPage || disabled}
            onClick={() => fetchNextPage()}
          >
            {isFetchingNextPage ? <Spinner /> : null}
            {isError
              ? t("retry", { unit: noun })
              : (loadMoreLabel ?? t("loadMore", { unit: noun }))}
          </Button>
        </>
      ) : null}
    </div>
  );
}
