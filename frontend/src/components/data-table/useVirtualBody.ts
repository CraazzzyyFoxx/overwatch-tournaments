"use client";

import type { Row } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";

import type { AdminDataTableGroup, AdminDataTableProps } from "@/components/data-table/types";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";

/**
 * Rows past which the body is virtualised. Below it every row is in the DOM,
 * which keeps find-in-page and the tests' plain DOM queries working; above it
 * an infinite list of a few hundred `<tr>`s starts stuttering on scroll.
 */
const VIRTUALIZE_FROM = 100;
const ROW_HEIGHT_ESTIMATE: Record<AdminTableDensity, number> = { comfortable: 41, compact: 33 };

/** One flat list of everything the body renders, so the virtualiser can measure group headers and expanded details like any other row. */
export type BodyItem<TData> =
  | { kind: "group"; key: string; group: AdminDataTableGroup<TData> }
  | { kind: "row"; key: string; row: Row<TData> }
  | { kind: "detail"; key: string; row: Row<TData> };

export interface VirtualBodyOptions<TData> extends Pick<AdminDataTableProps<TData>, "groupRows"> {
  pageRows: Row<TData>[];
  /** `renderExpanded` was given, so an expanded row contributes a detail item. */
  hasExpandedDetail: boolean;
  isMobile: boolean;
  density: AdminTableDensity;
  scrollElement: HTMLElement | null;
}

/** The body's render list and, past `VIRTUALIZE_FROM` rows, the window of it that is actually mounted. */
export function useVirtualBody<TData>({
  pageRows,
  groupRows,
  hasExpandedDetail,
  isMobile,
  density,
  scrollElement
}: VirtualBodyOptions<TData>) {
  const rowGroups = groupRows
    ? groupRows(pageRows)
    : [{ key: "all", label: null, rows: pageRows }];

  const bodyItems: BodyItem<TData>[] = rowGroups.flatMap((group) => [
    ...(group.label !== null ? [{ kind: "group" as const, key: `group:${group.key}`, group }] : []),
    ...group.rows.flatMap((row) => [
      { kind: "row" as const, key: row.id, row },
      ...(hasExpandedDetail && row.getIsExpanded() ? [{ kind: "detail" as const, key: `detail:${row.id}`, row }] : [])
    ])
  ]);

  const virtualize = !isMobile && bodyItems.length > VIRTUALIZE_FROM;
  const virtualizer = useVirtualizer({
    count: bodyItems.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => ROW_HEIGHT_ESTIMATE[density],
    getItemKey: (index) => bodyItems[index].key,
    overscan: 12,
    enabled: virtualize
  });
  const virtualItems = virtualize ? virtualizer.getVirtualItems() : [];

  return {
    rowGroups,
    bodyItems,
    virtualize,
    virtualizer,
    virtualItems,
    padTop: virtualItems[0]?.start ?? 0,
    padBottom: virtualItems.length > 0 ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end : 0,
    firstRowId: bodyItems.find((item) => item.kind === "row")?.row.id ?? null
  };
}
