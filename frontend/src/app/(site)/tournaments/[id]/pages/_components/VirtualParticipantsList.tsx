"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslations } from "next-intl";

import BattleTagRankHistory from "@/components/BattleTagRankHistory";
import { cn } from "@/lib/utils";
import type { Registration } from "@/types/registration.types";

import styles from "../../TournamentDetail.module.css";
import type { ColumnDefinition } from "./participantsColumns";
import { isMandatoryParticipantColumnId } from "./participants-url-state";

const ESTIMATED_ROW_HEIGHT = 68;

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

export default function VirtualParticipantsList({
  registrations,
  allColumns,
  visibleColumns,
  expandedIds,
  onToggleExpanded,
}: VirtualParticipantsListProps) {
  const t = useTranslations();
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
  const secondaryColumnCount = Math.max(displayColumns.length - 1, 0);
  const gridStyle = {
    "--participant-grid-columns":
      displayColumns.length > 0
        ? `minmax(12rem, 1.4fr) repeat(${secondaryColumnCount}, minmax(8rem, 1fr)) 3rem`
        : "3rem",
    "--participant-table-min-width": `${Math.max(46, displayColumns.length * 8 + 7)}rem`,
  } as CSSProperties;

  return (
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
              )}
              data-column-id={column.id}
              data-participant-kind={
                index === 0 ? "identity" : column.id === "_status" ? "status" : "detail"
              }
              key={column.id}
              role="columnheader"
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
          style={{ height: virtualizer.getTotalSize() }}
        >
          {virtualItems.map((item) => {
            const registration = registrations[item.index];
            const expanded = expandedIds.has(registration.id);
            const detailsId = `participant-details-${registration.id}`;
            const expanderId = `participant-expander-${registration.id}`;

            return (
              <div
                className={styles.participantVirtualRow}
                data-expanded={expanded ? "true" : "false"}
                data-index={item.index}
                key={item.key}
                ref={virtualizer.measureElement}
                style={{ transform: `translateY(${item.start - scrollMargin}px)` }}
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
                    <button
                      aria-controls={detailsId}
                      aria-expanded={expanded}
                      aria-label={expanded ? t("common.collapse") : t("common.expand")}
                      className={styles.participantExpander}
                      id={expanderId}
                      onClick={(event) => {
                        onToggleExpanded(registration.id);
                        if (expanded) event.currentTarget.focus();
                      }}
                      type="button"
                    >
                      <span className={styles.participantExpanderLabel}>
                        {expanded
                          ? t("common.collapse")
                          : t("registration.myCard.details")}
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
                    <div
                      aria-labelledby={expanderId}
                      className={styles.participantExpandedRegion}
                      id={detailsId}
                      role="region"
                    >
                      <div className={styles.participantRankHistory}>
                        <div className={styles.participantDetailLabel}>
                          {t("tournamentDetail.rankHistory")}
                        </div>
                        <BattleTagRankHistory
                          battleTag={registration.battle_tag}
                          userId={registration.user_id}
                        />
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
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
