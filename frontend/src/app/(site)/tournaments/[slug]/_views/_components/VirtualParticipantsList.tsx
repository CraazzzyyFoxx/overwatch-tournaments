"use client";

import { memo, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";

import RankHistory from "@/components/RankHistory";
import { cn } from "@/lib/utils";
import type { Registration } from "@/types/registration.types";

import { IDENTITY_COLUMN_ID, type ColumnDefinition } from "./participantsColumns.model";
import { isMandatoryParticipantColumnId } from "./participants-url-state";

const ESTIMATED_ROW_HEIGHT = 56;

/**
 * Desktop grid track budget per content class, in rem. Every row is its own
 * grid, so a track minimum has to be declared rather than measured — a
 * content-based track would resolve per row and the columns would drift apart.
 * Each value is the widest of its rendered content and its longest localized
 * header, measured at the cell's own inline padding:
 *   data   free text and multi-chip cells
 *   badge  one nowrap status pill ("Не добавлен" is the widest common one at
 *          97px) or three 32px role icons
 *   icon   a single 20px glyph under the longest header ("SUBSCRIPTION", 87px)
 * A flat 8rem for every column pushed the table to 103rem the moment the
 * subscription column landed, which is wider than a 1600px window.
 */
const COLUMN_TRACKS = {
  identity: { min: 12, grow: 1.4 },
  data: { min: 8, grow: 1 },
  badge: { min: 7.25, grow: 0.7 },
  icon: { min: 6.75, grow: 0.5 },
} as const;

/** Fixed expander track; holds the 2.25rem `icon` button. */
const EXPANDER_TRACK_REM = 3;

/** A column head: the `ui/table` head voice, ellipsized in a narrow track. */
const HEAD_CELL = eyebrowClass("faint", "min-w-0 truncate px-3.5 py-2.75");

/** A body cell: the `ui/table` cell voice. */
const BODY_CELL = "min-w-0 px-3.5 py-1.75 text-caption text-[color:var(--aqt-fg-muted)] wrap-anywhere";

type CellKind = "identity" | "status" | "detail";

/** The first column is the row's identity; a phone shows it and the status, and folds the rest. */
function cellKind(column: ColumnDefinition, index: number): CellKind {
  if (index === 0) return "identity";
  return column.id === "_status" ? "status" : "detail";
}

/** Badge and icon tracks are narrow by design: a full gutter would eat more of them than the content does. */
function isCompactColumn(column: ColumnDefinition, index: number): boolean {
  return index > 0 && column.width != null && column.width !== "data";
}

function orderedColumns(
  visibleColumns: readonly ColumnDefinition[],
  allColumns: readonly ColumnDefinition[],
): ColumnDefinition[] {
  const visibleIds = new Set(visibleColumns.map((column) => column.id));
  // Mandatory columns render even when deselected; everything else keeps the
  // canonical build order instead of being regrouped around the mandatory set.
  const display = allColumns.filter(
    (column) =>
      isMandatoryParticipantColumnId(column.id) || visibleIds.has(column.id),
  );
  // The identity column stays leftmost: the grid gives the first track its
  // wide minmax and the mobile card layout promotes cell 0 to the title row.
  return [
    ...display.filter((column) => column.id === IDENTITY_COLUMN_ID),
    ...display.filter((column) => column.id !== IDENTITY_COLUMN_ID),
  ];
}

/**
 * Native find-in-page only sees mounted rows, so the virtual window hides most
 * participants from Ctrl+F. The keydown is observed without preventDefault: the
 * browser still opens its own find bar, and by the time anything is typed the
 * list has re-rendered every row in normal flow (kept cheap by
 * `content-visibility: auto`).
 */
function useFindInPageMode(): boolean {
  const [findMode, setFindMode] = useState(false);

  useEffect(() => {
    if (findMode) return;
    // event.code, not event.key: on a Cyrillic layout the F key reports "а".
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code === "KeyF" && (event.ctrlKey || event.metaKey) && !event.altKey) {
        setFindMode(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [findMode]);

  // ponytail: one-way switch — once the visitor searched, keep the full DOM for
  // the rest of the visit instead of tracking when the find bar closes.
  return findMode;
}

function useDocumentScrollMargin() {
  const listStartRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<number | null>(null);
  const [scrollMargin, setScrollMargin] = useState(0);

  useEffect(() => {
    const element = listStartRef.current;
    if (!element) return;

    const measure = () => {
      frameRef.current = null;
      const nextMargin = Math.round(element.getBoundingClientRect().top + window.scrollY);
      setScrollMargin((current) => (current === nextMargin ? current : nextMargin));
    };
    const scheduleMeasure = () => {
      if (frameRef.current === null) frameRef.current = window.requestAnimationFrame(measure);
    };

    const observer = new ResizeObserver(scheduleMeasure);
    observer.observe(element);
    if (element.parentElement) observer.observe(element.parentElement);
    const layoutBoundary = element.closest("[data-participant-layout]");
    if (layoutBoundary) observer.observe(layoutBoundary);
    observer.observe(document.documentElement);
    window.addEventListener("resize", scheduleMeasure);
    scheduleMeasure();

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
    };
  }, []);

  return { listStartRef, scrollMargin };
}

interface VirtualParticipantsListProps {
  registrations: Registration[];
  allColumns: ColumnDefinition[];
  visibleColumns: ColumnDefinition[];
  expandedIds: ReadonlySet<number>;
  onToggleExpanded: (registrationId: number) => void;
  /** The tournament's game: rank history is resolved for it. */
  discipline: string;
}

const VirtualParticipantsList = memo(function VirtualParticipantsList({
  registrations,
  allColumns,
  visibleColumns,
  expandedIds,
  onToggleExpanded,
  discipline,
}: VirtualParticipantsListProps) {
  const t = useTranslations();
  const findMode = useFindInPageMode();
  const { listStartRef, scrollMargin } = useDocumentScrollMargin();
  const displayColumns = useMemo(
    () => orderedColumns(visibleColumns, allColumns),
    [allColumns, visibleColumns],
  );
  const displayColumnIds = useMemo(
    () => new Set(displayColumns.map((column) => column.id)),
    [displayColumns],
  );
  const hiddenColumns = useMemo(
    () =>
      allColumns.filter(
        (column) => column.id !== "_index" && !displayColumnIds.has(column.id),
      ),
    [allColumns, displayColumnIds],
  );
  const virtualizer = useWindowVirtualizer({
    count: registrations.length,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    getItemKey: (index) => registrations[index].id,
    overscan: 8,
    scrollMargin,
  });
  const virtualItems = virtualizer.getVirtualItems();
  const rows = findMode
    ? registrations.map((registration, index) => ({ index, key: registration.id, start: 0 }))
    : virtualItems;
  // The first column is the identity track regardless of which field lands
  // there; the rest are sized by their declared content class.
  const tracks = displayColumns.map((column, index) =>
    index === 0 ? COLUMN_TRACKS.identity : COLUMN_TRACKS[column.width ?? "data"],
  );
  const gridStyle = {
    "--participant-grid-columns": [
      ...tracks.map((track) => `minmax(${track.min}rem, ${track.grow}fr)`),
      `${EXPANDER_TRACK_REM}rem`,
    ].join(" "),
    // Must equal the sum of the track minimums: any smaller value lets the
    // viewport squeeze tracks below their minmax floor and the table overflows
    // without a scrollbar to reach the clipped columns.
    "--participant-table-min-width": `${
      tracks.reduce((total, track) => total + track.min, 0) + EXPANDER_TRACK_REM
    }rem`,
  } as CSSProperties;

  return (
    <TooltipProvider>
      {/* The table's own horizontal scroll owner, so a table wider than the
          viewport never widens the document; `@container` lets the details
          panel size itself to this box's visible width. One bordered list
          with hairline rows on a phone too: the virtualizer measures border
          boxes, so a margin between rows would overlap the next one. */}
      <Card className="@container w-full min-w-0 max-w-full overflow-x-auto overflow-y-clip overscroll-x-contain [contain:paint] [scrollbar-width:thin] max-sm:overflow-x-hidden">
      <div
        className="w-full min-w-[max(100%,var(--participant-table-min-width))] max-sm:min-w-0"
        role="table"
        aria-rowcount={registrations.length + 1}
        style={gridStyle}
      >
        <div
          className="grid min-h-10 w-full grid-cols-[var(--participant-grid-columns)] items-center border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] max-sm:sr-only"
          role="row"
          aria-rowindex={1}
        >
          {displayColumns.map((column, index) => {
            const kind = cellKind(column, index);
            return (
              <div
                className={cn(
                  HEAD_CELL,
                  kind === "detail" && "max-sm:hidden",
                  column.align === "center" && "text-center",
                  isCompactColumn(column, index) && "px-2",
                )}
                data-column-id={column.id}
                data-participant-kind={kind}
                key={column.id}
                role="columnheader"
                // Narrow tracks ellipsize the longest localized labels
                // ("Subscription", "Балансировщик"); the tooltip is the only way
                // back to the full name on a pointer device.
                title={column.label}
              >
                {column.label}
              </div>
            );
          })}
          <div className={HEAD_CELL} role="columnheader">
            <span className="sr-only">{t("registration.myCard.details")}</span>
          </div>
        </div>

        <div
          className="relative w-full"
          ref={listStartRef}
          style={findMode ? undefined : { height: virtualizer.getTotalSize() }}
        >
          {rows.map((item) => {
            const registration = registrations[item.index];
            const expanded = expandedIds.has(registration.id);
            const detailsId = `participant-details-${registration.id}`;
            const expanderId = `participant-expander-${registration.id}`;

            return (
              <div
                className={cn(
                  "absolute left-0 top-0 w-full border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] transition-colors [contain:layout_style] hover:bg-[color:var(--aqt-overlay-2)]",
                  // Find-in-page mode: every row is mounted in normal flow so
                  // the browser's own search can reach it, while offscreen rows
                  // skip layout and paint. 55px content + the 1px hairline keeps
                  // an unrendered row at the ESTIMATED_ROW_HEIGHT the
                  // virtualizer used, so switching modes while scrolled does
                  // not move the page.
                  findMode && "static [content-visibility:auto] [contain-intrinsic-size:auto_55px]",
                )}
                data-expanded={expanded ? "true" : "false"}
                data-index={item.index}
                key={item.key}
                ref={findMode ? undefined : virtualizer.measureElement}
                style={
                  findMode ? undefined : { transform: `translateY(${item.start - scrollMargin}px)` }
                }
              >
                {/* A phone stacks the row as a card: identity over status on
                    the left, the expander on the right, and the detail cells
                    only while the row is open. */}
                <div
                  aria-rowindex={item.index + 2}
                  className="grid min-h-13 w-full grid-cols-[var(--participant-grid-columns)] items-center max-sm:min-h-16 max-sm:grid-cols-[minmax(0,1fr)_auto] max-sm:gap-x-3 max-sm:py-2 max-sm:pl-3.5 max-sm:pr-1.5"
                  role="row"
                >
                  {displayColumns.map((column, index) => {
                    const kind = cellKind(column, index);
                    return (
                      <div
                        className={cn(
                          BODY_CELL,
                          column.align === "center" && "text-center",
                          isCompactColumn(column, index) && "px-2",
                          "max-sm:flex max-sm:items-center max-sm:gap-2.25 max-sm:px-0 max-sm:py-0.5 max-sm:text-left",
                          kind === "identity" &&
                            "max-sm:col-start-1 max-sm:row-start-1 max-sm:text-body max-sm:font-semibold max-sm:text-[color:var(--aqt-fg)]",
                          kind === "status" &&
                            cn("max-sm:col-start-1 max-sm:row-start-2", expanded && "max-sm:pb-2.5"),
                          kind === "detail" && (expanded ? "max-sm:col-span-full" : "max-sm:hidden"),
                        )}
                        data-column-id={column.id}
                        data-participant-kind={kind}
                        key={column.id}
                        role="cell"
                      >
                        {/* Sentence case and whole words on a phone: a tracked
                            uppercase label in a 7.5rem column split long words
                            mid-word. The identity and status cells need no
                            visible label; it stays for screen readers. */}
                        <span
                          className={cn(
                            "hidden max-sm:inline",
                            kind === "detail"
                              ? "max-sm:flex-[0_0_7.5rem] max-sm:text-caption max-sm:font-medium max-sm:text-[color:var(--aqt-fg-dim)] max-sm:wrap-break-word"
                              : "max-sm:sr-only",
                          )}
                        >
                          {column.label}
                        </span>
                        <div className="min-w-0">
                          {column.render(registration, item.index)}
                        </div>
                      </div>
                    );
                  })}
                  <div
                    className={cn(
                      BODY_CELL,
                      "grid place-items-center px-1.5 max-sm:col-start-2 max-sm:row-span-2 max-sm:row-start-1 max-sm:self-center max-sm:px-0 max-sm:py-0.5",
                    )}
                    role="cell"
                  >
                    {/* One name, whatever the state: `aria-expanded` and the
                        chevron carry open/closed, and the details region below
                        borrows this name via `aria-labelledby`, so a toggling
                        "Collapse" here would name the region "Collapse". Icon
                        only on a phone too, at a 44px touch target. */}
                    <Button
                      aria-controls={detailsId}
                      aria-expanded={expanded}
                      aria-label={t("registration.myCard.details")}
                      className="text-[color:var(--aqt-fg-dim)] max-sm:min-h-11 max-sm:min-w-11"
                      id={expanderId}
                      onClick={(event) => {
                        onToggleExpanded(registration.id);
                        if (expanded) event.currentTarget.focus();
                      }}
                      size="icon"
                      type="button"
                      variant="ghost"
                    >
                      {expanded ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
                    </Button>
                  </div>
                </div>

                {expanded ? (
                  <div className="min-w-0">
                    {/* The table can be wider than its scroller: the panel
                        takes the scroller's visible width and stays pinned
                        while the columns above it scroll, so its right column
                        never sits past the visible edge. */}
                    <section
                      aria-labelledby={expanderId}
                      className="sticky left-0 grid w-[100cqi] grid-cols-[minmax(0,3fr)_minmax(12rem,1fr)] gap-4 border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] p-4 max-sm:grid-cols-1 max-sm:p-3.5"
                      id={detailsId}
                    >
                      <div className="grid min-w-0 content-start gap-2">
                        <Eyebrow as="div" tone="dim">
                          {t("tournamentDetail.rankHistory")}
                        </Eyebrow>
                        {registration.user_id != null ? (
                          <RankHistory userId={registration.user_id} discipline={discipline} framed={false} />
                        ) : (
                          <RankHistory battleTag={registration.primary_handle} discipline={discipline} framed={false} />
                        )}
                      </div>
                      <div className="grid min-w-0 content-start gap-3">
                        <Eyebrow as="div" tone="dim">
                          {t("registration.myCard.details")}
                        </Eyebrow>
                        {hiddenColumns.length === 0 ? (
                          <p className="text-label italic text-[color:var(--aqt-fg-dim)]">
                            {t("tournamentDetail.allFieldsVisible")}
                          </p>
                        ) : (
                          hiddenColumns.map((column) => (
                            <div
                              className="grid min-w-0 gap-0.75 text-label text-[color:var(--aqt-fg)] wrap-anywhere"
                              key={column.id}
                            >
                              {/* The organizer's own question, often a full
                                  line or three: it reads as written, not as a
                                  tracked all-caps heading. */}
                              <div className="font-medium leading-[1.4] text-[color:var(--aqt-fg-dim)]">
                                {column.label}
                              </div>
                              <div>{column.render(registration, item.index)}</div>
                            </div>
                          ))
                        )}
                      </div>
                    </section>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      </Card>
    </TooltipProvider>
  );
});

export default VirtualParticipantsList;
