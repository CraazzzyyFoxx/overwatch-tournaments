"use client";

import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChevronDown, ChevronUp, ExternalLink, X } from "lucide-react";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";

export interface InspectorProps {
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

/** `lg` in `globals.css`'s `@theme` — the width at which the panel fits beside a table. */
const PANEL_MEDIA_QUERY = "(min-width: 1024px)";

/** Panel width bounds in px. One width for every screen: it is the reader's preference, not the data's. */
const PANEL_WIDTH = { min: 320, max: 720, initial: 380, step: 16 } as const;
const PANEL_WIDTH_KEY = "admin-inspector-width";
const clampWidth = (width: number) =>
  Math.min(PANEL_WIDTH.max, Math.max(PANEL_WIDTH.min, Number.isFinite(width) ? width : PANEL_WIDTH.initial));

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
export function Inspector({
  openId,
  onClose,
  title,
  subtitle,
  actions,
  children,
  onPrev,
  onNext,
  openHref
}: Readonly<InspectorProps>) {
  const t = useTranslations("kit.actions");
  const isWide = useMediaQuery(PANEL_MEDIA_QUERY);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const isOpen = openId !== null;
  const [savedWidth, setSavedWidth] = useLocalStorageState<number>(PANEL_WIDTH_KEY, PANEL_WIDTH.initial);
  // Live width while dragging; persisted once on release, not on every pointer move.
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  // `last` is read on release: the state may not have re-rendered since the final move.
  const drag = useRef<{ x: number; width: number; last: number } | null>(null);
  const endDrag = (save: boolean) => {
    if (save && drag.current) setSavedWidth(drag.current.last);
    drag.current = null;
    setDragWidth(null);
  };
  const width = clampWidth(dragWidth ?? savedWidth);

  const handleResizeKey = (event: ReactKeyboardEvent) => {
    // The handle sits on the left edge: Left widens, Right narrows.
    const delta = { ArrowLeft: PANEL_WIDTH.step, ArrowRight: -PANEL_WIDTH.step }[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    setSavedWidth(clampWidth(width + delta));
  };

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      // A dialog over the inspector (the notes sheet, an image viewer, a confirm) owns its keys: Esc
      // closes that layer only, and ↑/↓ must not page the row out from under it. The inspector's own
      // sheet below `lg` is not such a layer.
      const layer =
        event.target instanceof Element ? event.target.closest('[role="dialog"], [role="alertdialog"]') : null;
      if (layer && !layer.hasAttribute("data-inspector-sheet")) return;
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
          className="truncate font-display text-base font-semibold text-foreground outline-hidden"
        >
          {title}
        </h2>
        {subtitle ? (
          <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {onPrev ? (
          <Button variant="ghost" size="icon-sm" aria-label={t("previousRow")} onClick={onPrev}>
            <ChevronUp aria-hidden />
          </Button>
        ) : null}
        {onNext ? (
          <Button variant="ghost" size="icon-sm" aria-label={t("nextRow")} onClick={onNext}>
            <ChevronDown aria-hidden />
          </Button>
        ) : null}
        {showClose ? (
          <Button variant="ghost" size="icon-sm" aria-label={t("closeInspector")} onClick={onClose}>
            <X aria-hidden />
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
                {t("openPage")}
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
        <SheetContent side="right" variant="panel" className="w-full max-w-none sm:max-w-none" data-inspector-sheet>
          <SheetTitle className="sr-only">{typeof title === "string" ? title : t("details")}</SheetTitle>
          <SheetDescription className="sr-only">
            {t("detailsSelectedRow")}
          </SheetDescription>
          {renderHeader(false)}
          {body}
        </SheetContent>
      </Sheet>
    );
  }

  // `contain: size` + `self-stretch`: the panel adds no height to the grid row,
  // so the table alone sets it and the panel fills it, scrolling inside. Sized
  // by its own content it outgrew the viewport-fitted table and the page grew a
  // second scrollbar. `min-h-80` keeps a one-row table from crushing it. The
  // explicit width is what the screen's `auto` grid column sizes to.
  return (
    <Card
      asChild
      className="sticky top-16 flex min-h-80 max-h-[calc(100dvh-6rem)] max-w-[50vw] flex-col self-stretch overflow-hidden [contain:size]"
      style={{ width }}
    >
      <aside aria-label={t("rowInspector")} data-inspector-mode="panel">
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t("resizeInspector")}
          aria-valuemin={PANEL_WIDTH.min}
          aria-valuemax={PANEL_WIDTH.max}
          aria-valuenow={width}
          tabIndex={0}
          className="absolute inset-y-0 left-0 z-10 w-1.5 cursor-col-resize touch-none outline-hidden transition-colors hover:bg-primary/40 focus-visible:bg-primary/60"
          onKeyDown={handleResizeKey}
          onDoubleClick={() => setSavedWidth(PANEL_WIDTH.initial)}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            drag.current = { x: event.clientX, width, last: width };
          }}
          onPointerMove={(event) => {
            if (!drag.current) return;
            drag.current.last = clampWidth(drag.current.width + drag.current.x - event.clientX);
            setDragWidth(drag.current.last);
          }}
          onPointerUp={() => endDrag(true)}
          onPointerCancel={() => endDrag(false)}
        />
        {renderHeader(true)}
        {body}
      </aside>
    </Card>
  );
}
