"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, ExternalLink, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export interface AdminInspectorProps {
  /** The row currently open, read from `?id=` by the screen. `null` closes. */
  openId: string | null;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Entity actions live here, not in the table row. */
  actions?: ReactNode;
  children: ReactNode;
  onPrev?: () => void;
  onNext?: () => void;
  /** Route for this entity, when it has one. Renders "Open page". */
  openHref?: string;
}

/** `lg` in `tailwind.config.ts` — the width at which the panel fits beside a table. */
const PANEL_MEDIA_QUERY = "(min-width: 1024px)";

function useIsWideViewport(): boolean {
  const [isWide, setIsWide] = useState(false);

  useEffect(() => {
    const query = window.matchMedia(PANEL_MEDIA_QUERY);
    const sync = () => setIsWide(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return isWide;
}

/** Arrow keys must not steal caret movement inside a field in the inspector. */
function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * The row detail surface for every T2 browser.
 *
 * On `lg` and up it is a panel inside the content grid, so the table narrows
 * instead of being covered — investigating row 8812 keeps rows 8810–8814
 * visible (F2). Below `lg` there is no room for two columns, so the same
 * content becomes a full-screen sheet.
 *
 * `openId` is owned by the caller (it is `?id=` in the URL); this component
 * only renders. That keeps one writer for the query string per screen.
 */
export function AdminInspector({
  openId,
  onClose,
  title,
  subtitle,
  actions,
  children,
  onPrev,
  onNext,
  openHref
}: Readonly<AdminInspectorProps>) {
  const isWide = useIsWideViewport();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const isOpen = openId !== null;

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (isTextEntry(event.target)) return;
      if (event.key === "ArrowUp" && onPrev) {
        event.preventDefault();
        onPrev();
      }
      if (event.key === "ArrowDown" && onNext) {
        event.preventDefault();
        onNext();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose, onPrev, onNext]);

  // Panel mode has no focus trap (the table stays operable), so focus is only
  // moved to the heading on open and handed back to the row on close. The
  // sheet gets both from Radix.
  //
  // Two effects, not one: keyed on `openId`, the hand-back would run on every
  // row switch and throw focus to the row that first opened the panel —
  // scrolling the page there, which from row 500 reads as being yanked back to
  // the top of the table. It belongs to open/close alone. This one runs first
  // so it captures the row, not the heading the effect below focuses.
  useEffect(() => {
    if (!isOpen || !isWide) return;
    const opener = document.activeElement;
    return () => {
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [isOpen, isWide]);

  // `preventScroll`: the panel is sticky, so it is already on screen — letting
  // focus scroll it into view would yank the reader from row 8812 back to the
  // top of the table on every row click.
  useEffect(() => {
    if (!isOpen || !isWide) return;
    headingRef.current?.focus({ preventScroll: true });
  }, [isOpen, isWide, openId]);

  if (!isOpen) return null;

  /** `showClose` is off in sheet mode: Radix's own close sits in the same
   *  corner, so a second one would overlap it. Esc closes either way. */
  const renderHeader = (showClose: boolean) => (
    <div
      className={cn(
        "flex items-start gap-2 border-b border-border px-4 py-3",
        !showClose && "pr-12"
      )}
    >
      <div className="min-w-0 flex-1">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="truncate font-display text-base font-semibold text-foreground outline-none"
        >
          {title}
        </h2>
        {subtitle ? (
          <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {onPrev ? (
          <Button variant="ghost" size="icon" className="size-7" aria-label="Previous row" onClick={onPrev}>
            <ChevronUp aria-hidden className="size-4" />
          </Button>
        ) : null}
        {onNext ? (
          <Button variant="ghost" size="icon" className="size-7" aria-label="Next row" onClick={onNext}>
            <ChevronDown aria-hidden className="size-4" />
          </Button>
        ) : null}
        {showClose ? (
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label="Close inspector"
            onClick={onClose}
          >
            <X aria-hidden className="size-4" />
          </Button>
        ) : null}
      </div>
    </div>
  );

  const body = (
    <>
      {actions || openHref ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
          {actions}
          {openHref ? (
            <Button asChild variant="outline" size="sm">
              <Link href={openHref}>
                <ExternalLink aria-hidden className="size-3.5" />
                Open page
              </Link>
            </Button>
          ) : null}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
    </>
  );

  if (!isWide) {
    return (
      <Sheet open onOpenChange={(next) => (next ? undefined : onClose())}>
        <SheetContent
          side="right"
          className="flex w-full max-w-none flex-col gap-0 p-0 sm:max-w-none"
        >
          <SheetTitle className="sr-only">{typeof title === "string" ? title : "Details"}</SheetTitle>
          <SheetDescription className="sr-only">
            Details for the selected row.
          </SheetDescription>
          {renderHeader(false)}
          {body}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <aside
      aria-label="Row inspector"
      data-inspector-mode="panel"
      className={cn(
        "flex max-h-[calc(100dvh-6rem)] flex-col overflow-hidden rounded-xl border border-border bg-card",
        "sticky top-16 animate-in fade-in slide-in-from-right-2 duration-150 motion-reduce:animate-none"
      )}
    >
      {renderHeader(true)}
      {body}
    </aside>
  );
}
