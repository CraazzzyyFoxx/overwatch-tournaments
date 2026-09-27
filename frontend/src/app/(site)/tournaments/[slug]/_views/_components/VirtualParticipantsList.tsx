"use client";

import { memo, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { TooltipProvider } from "@/components/ui/tooltip";

import RankHistory from "@/components/RankHistory";
import { cn } from "@/lib/utils";
import type { Registration } from "@/types/registration.types";

import styles from "../../TournamentDetail.module.css";
import type { ColumnDefinition } from "./participantsColumns.model";
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

/** Fixed expander track; matches `.participantExpander`'s 2.25rem hit area. */
const EXPANDER_TRACK_REM = 3;

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
    ...display.filter((column) => column.id === "battle_tag"),
    ...display.filter((column) => column.id !== "battle_tag"),
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
}

const VirtualParticipantsList = memo(function VirtualParticipantsList({
  registrations,
  allColumns,
  visibleColumns,
  expandedIds,
  onToggleExpanded,
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
    <TooltipProvider delayDuration={150}>
      <div className={styles.participantsTableViewport}>
      <div
        className={styles.participantsTable}
        role="table"
        aria-rowcount={registrations.length + 1}
        style={gridStyle}
      >
        <div className={styles.participantHeaderRow} role="row" aria-rowindex={1}>
          {displayColumns.map((column, index) => (
            <div
              className={cn(
                styles.participantHeaderCell,
                index > 0 && column.id !== "_status" && styles.participantDetailCell,
                column.align === "center" && styles.participantCellCenter,
                index > 0 && column.width && column.width !== "data" &&
                  styles.participantCompactCell,
              )}
              data-column-id={column.id}
              data-participant-kind={
                index === 0 ? "identity" : column.id === "_status" ? "status" : "detail"
              }
              key={column.id}
              role="columnheader"
              // Narrow tracks ellipsize the longest localized labels
              // ("Subscription", "Балансировщик"); the tooltip is the only way
              // back to the full name on a pointer device.
              title={column.label}
            >
              {column.label}
            </div>
          ))}
          <div className={styles.participantHeaderCell} role="columnheader">
            <span className="sr-only">{t("registration.myCard.details")}</span>
          </div>
        </div>

        <div
          className={styles.participantVirtualSpacer}
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
                  styles.participantVirtualRow,
                  findMode && styles.participantStaticRow,
                )}
                data-expanded={expanded ? "true" : "false"}
                data-index={item.index}
                key={item.key}
                ref={findMode ? undefined : virtualizer.measureElement}
                style={
                  findMode ? undefined : { transform: `translateY(${item.start - scrollMargin}px)` }
                }
              >
                <div
                  aria-rowindex={item.index + 2}
                  className={styles.participantSummaryRow}
                  role="row"
                >
                  {displayColumns.map((column, index) => (
                    <div
                      className={cn(
                        styles.participantCell,
                        index > 0 && column.id !== "_status" && styles.participantDetailCell,
                        column.align === "center" && styles.participantCellCenter,
                        index > 0 && column.width && column.width !== "data" &&
                          styles.participantCompactCell,
                      )}
                      data-column-id={column.id}
                      data-participant-kind={
                        index === 0
                          ? "identity"
                          : column.id === "_status"
                            ? "status"
                            : "detail"
                      }
                      key={column.id}
                      role="cell"
                    >
                      <span className={styles.participantMobileCellLabel}>{column.label}</span>
                      <div className={styles.participantCellValue}>
                        {column.render(registration, item.index)}
                      </div>
                    </div>
                  ))}
                  <div className={styles.participantExpanderCell} role="cell">
                    {/* One name, whatever the state: `aria-expanded` and the
                        chevron carry open/closed, and the details region below
                        borrows this name via `aria-labelledby`, so a toggling
                        "Collapse" here would name the region "Collapse". */}
                    <button
                      aria-controls={detailsId}
                      aria-expanded={expanded}
                      aria-label={t("registration.myCard.details")}
                      className={styles.participantExpander}
                      id={expanderId}
                      onClick={(event) => {
                        onToggleExpanded(registration.id);
                        if (expanded) event.currentTarget.focus();
                      }}
                      type="button"
                    >
                      <span className={styles.participantExpanderLabel}>
                        {t("registration.myCard.details")}
                      </span>
                      {expanded ? (
                        <ChevronUp aria-hidden="true" className="size-4" />
                      ) : (
                        <ChevronDown aria-hidden="true" className="size-4" />
                      )}
                    </button>
                  </div>
                </div>

                {expanded ? (
                  <div className={styles.participantExpandedCell}>
                    <section
                      aria-labelledby={expanderId}
                      className={styles.participantExpandedRegion}
                      id={detailsId}
                    >
                      <div className={styles.participantRankHistory}>
                        <div className={styles.participantDetailLabel}>
                          {t("tournamentDetail.rankHistory")}
                        </div>
                        {registration.user_id != null ? (
                          <RankHistory userId={registration.user_id} />
                        ) : (
                          <RankHistory battleTag={registration.battle_tag} />
                        )}
                      </div>
                      <div className={styles.participantHiddenFields}>
                        <div className={styles.participantDetailLabel}>
                          {t("registration.myCard.details")}
                        </div>
                        {hiddenColumns.length === 0 ? (
                          <p className={styles.participantMutedDetail}>
                            {t("tournamentDetail.allFieldsVisible")}
                          </p>
                        ) : (
                          hiddenColumns.map((column) => (
                            <div className={styles.participantHiddenField} key={column.id}>
                              <div className={styles.participantDetailLabel}>{column.label}</div>
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
      </div>
    </TooltipProvider>
  );
});

export default VirtualParticipantsList;
